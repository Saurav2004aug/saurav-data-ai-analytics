"""Read-only database access with timeouts, for DuckDB (default) and SQLite (fallback)."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import pandas as pd


class QueryTimeout(RuntimeError):
    pass


class Database:
    def __init__(self, path: str | Path | None = None, timeout_s: float = 15.0):
        from .demo_db import default_db_path
        self.path = Path(path or os.getenv("SQLANALYST_DB", default_db_path()))
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found - run `python -m sqlanalyst.demo_db` first")
        self.timeout_s = timeout_s
        self.dialect = "duckdb" if self.path.suffix == ".duckdb" else "sqlite"
        if self.dialect == "duckdb":
            import duckdb
            # read-only, and no reading local files / network from inside SQL,
            # whatever the static guardrails might miss
            self.con = duckdb.connect(str(self.path), read_only=True,
                                      config={"enable_external_access": False})
        else:
            self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)

    # ------------------------------------------------------------------ #
    def tables(self) -> list[str]:
        if self.dialect == "duckdb":
            return [r[0] for r in self.con.execute("select table_name from information_schema.tables").fetchall()]
        return [r[0] for r in self.con.execute("select name from sqlite_master where type='table'").fetchall()]

    def column_types(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for t in self.tables():
            if self.dialect == "duckdb":
                rows = self.con.execute(
                    "select column_name, data_type from information_schema.columns where table_name = ?", [t]
                ).fetchall()
            else:
                rows = [(r[1], r[2] or "TEXT") for r in self.con.execute(f"pragma table_info('{t}')")]
            out[t] = {c: typ.upper() for c, typ in rows}
        return out

    # ------------------------------------------------------------------ #
    def query(self, sql: str) -> pd.DataFrame:
        if self.dialect == "duckdb":
            timer = threading.Timer(self.timeout_s, self.con.interrupt)
            timer.start()
            try:
                return self.con.execute(sql).df()
            except Exception as e:
                if "interrupt" in str(e).lower():
                    raise QueryTimeout(f"query exceeded {self.timeout_s}s") from e
                raise
            finally:
                timer.cancel()
        deadline = time.monotonic() + self.timeout_s
        self.con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cur = self.con.execute(sql)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e):
                raise QueryTimeout(f"query exceeded {self.timeout_s}s") from e
            raise
        finally:
            self.con.set_progress_handler(None, 0)
