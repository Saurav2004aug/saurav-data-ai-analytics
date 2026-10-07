"""A tiny, dependency-light dbt runner for SQLite, used for offline tests and CI smoke tests.

It is NOT a replacement for dbt. It renders the project's real model / test SQL with
Jinja, resolves ``ref`` / ``source`` / ``var`` / ``config`` / ``is_incremental``,
provides SQLite versions of the dbt cross-database macros the project uses, executes
models in dependency order and runs every generic + singular data test.

That lets the test suite prove the *business logic* of every model (joins, grain,
aggregations, reconciliations) on any machine with only Python installed. The real
build is still ``dbt build`` on DuckDB (see README and CI).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

import pandas as pd
import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt"
TABLES = {
    "olist_customers_dataset": "customers",
    "olist_orders_dataset": "orders",
    "olist_order_items_dataset": "order_items",
    "olist_order_payments_dataset": "order_payments",
    "olist_order_reviews_dataset": "order_reviews",
    "olist_products_dataset": "products",
    "olist_sellers_dataset": "sellers",
    "product_category_name_translation": "category_translation",
}
REF_RE = re.compile(r"ref\(\s*['\"](\w+)['\"]\s*\)")


# --------------------------------------------------------------------------- #
# SQLite implementations of dbt's cross-database macros
# --------------------------------------------------------------------------- #
class _DbtNamespace:
    type_timestamp = staticmethod(lambda: "TEXT")
    type_string = staticmethod(lambda: "TEXT")
    type_numeric = staticmethod(lambda: "REAL")
    type_int = staticmethod(lambda: "INTEGER")

    @staticmethod
    def date_trunc(datepart, date):
        if datepart == "month":
            return f"date({date}, 'start of month')"
        if datepart == "day":
            return f"date({date})"
        raise NotImplementedError(datepart)

    @staticmethod
    def datediff(first, second, datepart):
        if datepart == "day":
            return f"cast(julianday(date({second})) - julianday(date({first})) as integer)"
        if datepart == "month":
            return (f"((cast(strftime('%Y', {second}) as integer) - cast(strftime('%Y', {first}) as integer)) * 12"
                    f" + cast(strftime('%m', {second}) as integer) - cast(strftime('%m', {first}) as integer))")
        raise NotImplementedError(datepart)

    @staticmethod
    def dateadd(datepart, interval, from_date_or_timestamp):
        return f"datetime({from_date_or_timestamp}, '+' || ({interval}) || ' {datepart}')"


@dataclass
class TestResult:
    name: str
    failures: int
    status: str  # pass | warn | fail


@dataclass
class RunResult:
    models: list[str] = field(default_factory=list)
    tests: list[TestResult] = field(default_factory=list)

    @property
    def failed(self) -> list[TestResult]:
        return [t for t in self.tests if t.status == "fail"]


class SqliteDbt:
    def __init__(self, db_path: str | Path = ":memory:", dbt_dir: Path = DBT_DIR):
        self.dbt_dir = dbt_dir
        self.conn = sqlite3.connect(str(db_path))
        project = yaml.safe_load((dbt_dir / "dbt_project.yml").read_text())
        self.vars = project.get("vars", {})
        self.env = Environment(extensions=["jinja2.ext.do"])
        self.macro_src = self._load_macros()
        self.models = {p.stem: p for p in (dbt_dir / "models").rglob("*.sql")}
        self.seeds = {p.stem: p for p in (dbt_dir / "seeds").glob("*.csv")}

    # ---- jinja plumbing -----------------------------------------------------
    def _load_macros(self) -> str:
        parts = [p.read_text() for p in sorted((self.dbt_dir / "macros").rglob("*.sql"))]
        for p in sorted((self.dbt_dir / "tests" / "generic").glob("*.sql")):
            src = p.read_text()
            src = re.sub(r"{%-?\s*test\s+(\w+)\s*\(", r"{% macro test_\1(", src)
            src = re.sub(r"{%-?\s*endtest\s*-?%}", "{% endmacro %}", src)
            parts.append(src)
        return "\n".join(parts)

    def _render(self, sql: str, this: str = "", captured: dict | None = None) -> str:
        captured = {} if captured is None else captured

        def config(**kwargs):
            captured.update(kwargs)
            return ""

        def var(name, default=None):
            return self.vars.get(name, default)

        ctx = {
            "ref": lambda name: name,
            "source": lambda src, table: f"raw__{table}",
            "config": config,
            "var": var,
            "is_incremental": lambda: False,
            "this": this,
            "dbt": _DbtNamespace,
            "return": lambda x: x,
            "target": {"type": "sqlite", "name": "harness"},
        }
        module = self.env.from_string(self.macro_src).make_module(ctx)

        class _Adapter:
            @staticmethod
            def dispatch(name, macro_namespace=None):
                for prefix in ("sqlite__", "default__"):
                    macro = getattr(module, prefix + name, None)
                    if macro is not None:
                        return macro
                raise KeyError(name)

        ctx["adapter"] = _Adapter
        macros = {k: getattr(module, k) for k in dir(module) if not k.startswith("_")}
        ctx.update(macros)
        module = self.env.from_string(self.macro_src).make_module(ctx)  # re-bind with adapter
        ctx.update({k: getattr(module, k) for k in dir(module) if not k.startswith("_")})
        return self.env.from_string(sql).render(ctx)

    # ---- loading --------------------------------------------------------------
    def load_raw(self, raw_dir: str | Path) -> None:
        for stem, table in TABLES.items():
            df = pd.read_csv(Path(raw_dir) / f"{stem}.csv", dtype=str, keep_default_na=True)
            df.to_sql(f"raw__{table}", self.conn, if_exists="replace", index=False)

    def load_seeds(self) -> None:
        for name, path in self.seeds.items():
            pd.read_csv(path, dtype=str).to_sql(name, self.conn, if_exists="replace", index=False)

    # ---- models -----------------------------------------------------------------
    def dag(self) -> list[str]:
        graph = {}
        for name, path in self.models.items():
            deps = set(REF_RE.findall(path.read_text()))
            graph[name] = {d for d in deps if d in self.models}
        return list(TopologicalSorter(graph).static_order())

    def run_models(self) -> list[str]:
        order = self.dag()
        for name in order:
            sql = self._render(self.models[name].read_text(), this=name)
            self.conn.execute(f'drop table if exists "{name}"')
            try:
                self.conn.execute(f'create table "{name}" as {sql}')
            except sqlite3.Error as e:
                raise RuntimeError(f"model {name} failed: {e}\n---\n{sql}") from e
        self.conn.commit()
        return order

    # ---- tests ------------------------------------------------------------------
    def _generic_sql(self, test, model: str, column: str) -> tuple[str, str]:
        if isinstance(test, str):
            kind, args = test, {}
        else:
            kind, args = next(iter(test.items()))
            args = args or {}
        if kind == "unique":
            sql = (f"select {column} from {model} where {column} is not null "
                   f"group by {column} having count(*) > 1")
        elif kind == "not_null":
            sql = f"select * from {model} where {column} is null"
        elif kind == "accepted_values":
            quote = args.get("quote", True)
            vals = ", ".join(f"'{v}'" if quote else str(v) for v in args["values"])
            sql = f"select * from {model} where {column} is not null and {column} not in ({vals})"
        elif kind == "relationships":
            parent = REF_RE.search(args["to"]).group(1)
            sql = (f"select c.{column} from {model} c left join {parent} p "
                   f"on c.{column} = p.{args['field']} "
                   f"where c.{column} is not null and p.{args['field']} is null")
        else:  # project-defined generic test macro
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            call = f"{{{{ test_{kind}(model='{model}', column_name='{column}'{', ' + arg_str if arg_str else ''}) }}}}"
            sql = self._render(call)
        return kind, sql

    def run_tests(self) -> list[TestResult]:
        results = []
        for yml in (self.dbt_dir / "models").rglob("*.yml"):
            spec = yaml.safe_load(yml.read_text()) or {}
            targets = [(m["name"], m) for m in spec.get("models", [])]
            for src in spec.get("sources", []):
                targets += [(f"raw__{t['name']}", t) for t in src.get("tables", [])]
            for model, node in targets:
                for col in node.get("columns", []):
                    for test in col.get("data_tests", []):
                        kind, sql = self._generic_sql(test, model, col["name"])
                        n = self.conn.execute(f"select count(*) from ({sql})").fetchone()[0]
                        results.append(TestResult(f"{kind}:{model}.{col['name']}", n,
                                                  "pass" if n == 0 else "fail"))
        for path in (self.dbt_dir / "tests").glob("*.sql"):
            cfg: dict = {}
            sql = self._render(path.read_text(), captured=cfg)
            n = self.conn.execute(f"select count(*) from ({sql})").fetchone()[0]
            status = "pass"
            if n > 0:
                if cfg.get("severity") == "warn":
                    threshold = int(str(cfg.get("warn_if", ">0")).lstrip("!=><"))
                    status = "warn" if n > threshold else "pass"
                else:
                    status = "fail"
            results.append(TestResult(f"singular:{path.stem}", n, status))
        return results

    def build(self, raw_dir: str | Path) -> RunResult:
        self.load_raw(raw_dir)
        self.load_seeds()
        return RunResult(models=self.run_models(), tests=self.run_tests())

    def query(self, sql: str) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.conn)


if __name__ == "__main__":
    import argparse
    import time

    ap = argparse.ArgumentParser(description="Build the warehouse on SQLite and run all data tests.")
    ap.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--db", default=str(ROOT / "warehouse" / "olist_harness.sqlite"))
    args = ap.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    t0 = time.time()
    res = SqliteDbt(args.db).build(args.raw_dir)
    print(f"built {len(res.models)} models in {time.time() - t0:.1f}s")
    for t in res.tests:
        if t.status != "pass":
            print(f"  {t.status.upper():4s} {t.name} ({t.failures} rows)")
    counts = {s: sum(t.status == s for t in res.tests) for s in ("pass", "warn", "fail")}
    print(f"tests: {counts['pass']} passed, {counts['warn']} warned, {counts['fail']} failed")
    raise SystemExit(1 if res.failed else 0)
