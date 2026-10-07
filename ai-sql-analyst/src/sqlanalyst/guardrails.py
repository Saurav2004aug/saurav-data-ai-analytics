"""SQL guardrails: the model's SQL is untrusted input and is treated that way.

Layers (defence in depth):
1. static validation: one statement, SELECT/WITH only, no write/DDL/admin keywords,
   no file/network table functions (read_csv, read_parquet, httpfs, ...), only
   tables from the semantic catalog;
2. a row LIMIT wrapped around every query;
3. a read-only database connection and a query timeout (see db.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "merge", "drop", "alter", "create", "truncate", "replace",
    "grant", "revoke", "attach", "detach", "copy", "export", "import", "install", "load",
    "pragma", "vacuum", "call", "set", "reset", "checkpoint", "begin", "commit", "rollback",
}
FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_text",
    "read_blob", "glob", "parquet_scan", "sqlite_scan", "postgres_scan", "mysql_scan",
    "load_extension", "readfile", "writefile", "system",
}


class UnsafeSQLError(ValueError):
    """Security violation: never executed, never retried."""


class UnknownTableError(ValueError):
    """Schema hallucination (not a security issue): reported back to the model for a retry."""


@dataclass
class ValidatedSQL:
    sql: str            # cleaned statement (no comments / trailing semicolon)
    limited_sql: str    # wrapped with a row limit, ready to execute


def _strip(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql.strip().rstrip(";").strip()


def _mask_strings(sql: str) -> str:
    """Blank out string literals so keywords inside them ('drop shipping') aren't flagged."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def extract_sql(text: str) -> str:
    """Pull the SQL out of an LLM reply (```sql fenced block preferred)."""
    m = re.findall(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m[-1].strip()
    m = re.search(r"\b(with|select)\b.*", text, flags=re.DOTALL | re.IGNORECASE)
    return m.group(0).strip() if m else text.strip()


def validate(sql: str, allowed_tables: set[str], max_rows: int = 1000) -> ValidatedSQL:
    clean = _strip(sql)
    if not clean:
        raise UnsafeSQLError("empty query")
    masked = _mask_strings(clean)
    if ";" in masked:
        raise UnsafeSQLError("multiple statements are not allowed")
    first = masked.split(None, 1)[0].lower()
    if first not in {"select", "with"}:
        raise UnsafeSQLError(f"only SELECT queries are allowed (got {first.upper()})")
    words = set(re.findall(r"[a-z_]+", masked.lower()))
    bad = words & FORBIDDEN_KEYWORDS
    if bad:
        raise UnsafeSQLError(f"forbidden keyword(s): {', '.join(sorted(bad))}")
    funcs = {f.lower() for f in re.findall(r"([a-zA-Z_]+)\s*\(", masked)}
    bad = funcs & FORBIDDEN_FUNCTIONS
    if bad:
        raise UnsafeSQLError(f"forbidden function(s): {', '.join(sorted(bad))}")
    if re.search(r"\b(?:from|join)\s*['\"]", masked, flags=re.IGNORECASE):
        raise UnsafeSQLError("reading files by path is not allowed")

    from .catalog import tables_in_sql
    unknown = tables_in_sql(masked) - {t.lower() for t in allowed_tables}
    if unknown:
        raise UnknownTableError(f"unknown table(s): {', '.join(sorted(unknown))}. "
                                f"Available tables: {', '.join(sorted(allowed_tables))}")
    limited = f"SELECT * FROM (\n{clean}\n) AS q LIMIT {int(max_rows)}"
    return ValidatedSQL(clean, limited)
