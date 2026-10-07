"""Semantic catalog + retrieval of relevant schema and few-shot examples."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "semantic" / "catalog.yml"
EXAMPLES_PATH = ROOT / "semantic" / "examples.yml"

TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w]*)", re.IGNORECASE)


@dataclass
class Table:
    name: str
    description: str
    synonyms: list[str]
    columns: dict[str, str]

    def doc(self) -> str:
        """Text used for retrieval: name, description, synonyms, column names and docs."""
        cols = " ".join(f"{c.replace('_', ' ')} {d}" for c, d in self.columns.items())
        return f"{self.name.replace('_', ' ')} {self.description} {' '.join(self.synonyms)} {cols}"

    def ddl(self, column_types: dict[str, str] | None = None) -> str:
        column_types = column_types or {}
        lines = [f"-- {self.description}", f"CREATE TABLE {self.name} ("]
        for i, (c, d) in enumerate(self.columns.items()):
            comma = "," if i < len(self.columns) - 1 else ""
            lines.append(f"    {c} {column_types.get(c, '')}{comma}  -- {d}".replace("  ,", ","))
        lines.append(");")
        return "\n".join(lines)


class Catalog:
    def __init__(self, path: Path = CATALOG_PATH):
        spec = yaml.safe_load(path.read_text())
        self.business_rules: list[str] = spec.get("business_rules", [])
        self.relationships: list[str] = spec.get("relationships", [])
        self.pinned: list[str] = spec.get("pinned_tables", [])
        self.tables = {n: Table(n, t["description"], t.get("synonyms", []), t["columns"])
                       for n, t in spec["tables"].items()}

    def schema_text(self, tables: list[str] | None = None, column_types: dict | None = None) -> str:
        names = tables or list(self.tables)
        column_types = column_types or {}
        ddl = "\n\n".join(self.tables[n].ddl(column_types.get(n)) for n in names if n in self.tables)
        joins = [r for r in self.relationships
                 if all(side.split(".")[0].strip() in names for side in r.split("="))]
        if joins:
            ddl += "\n\n-- Join paths:\n" + "\n".join(f"-- {j}" for j in joins)
        return ddl

    def neighbours(self, table: str) -> set[str]:
        out = set()
        for r in self.relationships:
            a, b = (side.split(".")[0].strip() for side in r.split("="))
            if table == a:
                out.add(b)
            elif table == b:
                out.add(a)
        return out


def _stem(token: str) -> str:
    """Tiny plural stemmer: categories->category, orders->order, sellers->seller."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _analyzer():
    base = TfidfVectorizer(stop_words="english").build_analyzer()

    def analyze(text: str) -> list[str]:
        toks = [_stem(t) for t in base(text)]
        return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    return analyze


class SchemaRetriever:
    """Picks the tables most relevant to a question (TF-IDF over the semantic layer).

    With 6 tables the full schema would fit in a prompt, but real warehouses have
    hundreds; retrieval keeps prompts small and focused, and is measured separately
    (table recall@k) in the benchmark.
    """

    def __init__(self, catalog: Catalog, k: int = 3, min_score: float = 0.05):
        self.catalog, self.k, self.min_score = catalog, k, min_score
        self.names = list(catalog.tables)
        self.vec = TfidfVectorizer(analyzer=_analyzer(), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([catalog.tables[n].doc() for n in self.names])

    def scores(self, question: str) -> dict[str, float]:
        sims = cosine_similarity(self.vec.transform([question]), self.matrix).ravel()
        return dict(zip(self.names, sims))

    def retrieve(self, question: str) -> list[str]:
        s = self.scores(question)
        ranked = sorted(s, key=s.get, reverse=True)
        picked = [n for n in ranked[: self.k] if s[n] >= self.min_score] or ranked[:1]
        # Pinned core tables + join closure: a dimension is useless without the fact it joins to.
        for t in self.catalog.pinned:
            if t not in picked:
                picked.append(t)
        for t in list(picked):
            if t.startswith("dim_"):
                picked += [n for n in self.catalog.neighbours(t) if n not in picked]
        return picked


@dataclass
class Example:
    question: str
    sql: str


class ExampleRetriever:
    """Dynamic few-shot: the k most similar solved examples go into the prompt."""

    def __init__(self, path: Path = EXAMPLES_PATH, k: int = 3):
        self.examples = [Example(e["question"], e["sql"].strip()) for e in yaml.safe_load(path.read_text())]
        self.k = k
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([e.question for e in self.examples])

    def retrieve(self, question: str) -> list[Example]:
        sims = cosine_similarity(self.vec.transform([question]), self.matrix).ravel()
        return [self.examples[i] for i in np.argsort(sims)[::-1][: self.k]]


def tables_in_sql(sql: str) -> set[str]:
    """Physical tables referenced by a query (CTE names excluded)."""
    ctes = set(re.findall(r"\b(\w+)\s+AS\s*\(", sql, flags=re.IGNORECASE))
    # FROM inside EXTRACT(year FROM x), SUBSTRING(s FROM 1), TRIM(BOTH FROM s) is not a table
    scrubbed = re.sub(r"\b(extract|substring|trim|position|overlay)\s*\([^()]*\)", " ", sql,
                      flags=re.IGNORECASE)
    return {t.lower() for t in TABLE_RE.findall(scrubbed)} - {c.lower() for c in ctes}
