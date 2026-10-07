"""The text-to-SQL agent: question -> prompt -> SQL -> guardrails -> execute -> self-correct."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from .catalog import Catalog, ExampleRetriever, SchemaRetriever
from .charts import suggest_chart
from .db import Database
from .guardrails import UnsafeSQLError, extract_sql, validate
from .llm import LLM, cost_usd


@dataclass(frozen=True)
class Strategy:
    name: str
    schema: str = "retrieved"      # "full" | "retrieved"
    few_shot: int = 3              # number of retrieved examples (0 = zero-shot)
    max_retries: int = 2           # self-correction attempts after an execution error


STRATEGIES = {
    "zero_shot": Strategy("zero_shot", schema="full", few_shot=0, max_retries=0),
    "retrieval": Strategy("retrieval", schema="retrieved", few_shot=0, max_retries=0),
    "retrieval_fewshot": Strategy("retrieval_fewshot", schema="retrieved", few_shot=3, max_retries=0),
    "full": Strategy("full", schema="retrieved", few_shot=3, max_retries=2),
}

SYSTEM = """You are a senior data analyst. You translate business questions into a single {dialect} SQL query over the warehouse described below.

Rules:
- Output exactly one read-only SELECT (or WITH ... SELECT) statement in a ```sql code block, nothing else.
- Use only the tables and columns provided. Never invent columns.
- Follow the business definitions exactly:
{rules}
- Return only the columns needed to answer the question, with readable aliases.
- For "top N" questions, ORDER BY the ranking measure and LIMIT N.
- Round ratios/averages to 2 decimals only if the question implies a displayed number.
- If the question cannot be answered from this schema, output: ```sql
-- CANNOT_ANSWER: <short reason>
```"""


@dataclass
class Attempt:
    sql: str
    error: str | None = None


@dataclass
class Answer:
    question: str
    sql: str | None
    data: pd.DataFrame | None
    error: str | None
    attempts: list[Attempt] = field(default_factory=list)
    tables_used_in_prompt: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0
    chart: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.data is not None


class SQLAgent:
    def __init__(self, llm: LLM, db: Database, catalog: Catalog | None = None,
                 strategy: Strategy | str = "full", max_rows: int = 1000):
        self.llm, self.db = llm, db
        self.catalog = catalog or Catalog()
        self.strategy = STRATEGIES[strategy] if isinstance(strategy, str) else strategy
        self.schema_retriever = SchemaRetriever(self.catalog)
        self.example_retriever = ExampleRetriever()
        self.column_types = db.column_types()
        self.allowed = set(self.catalog.tables) & set(self.db.tables())
        self.max_rows = max_rows

    # ----------------------------------------------------------------- prompt
    def build_prompt(self, question: str) -> tuple[str, list[dict], list[str]]:
        tables = (list(self.catalog.tables) if self.strategy.schema == "full"
                  else self.schema_retriever.retrieve(question))
        system = SYSTEM.format(dialect={"duckdb": "DuckDB", "sqlite": "SQLite"}[self.db.dialect],
                               rules="\n".join(f"  * {r}" for r in self.catalog.business_rules))
        parts = ["### Schema", self.catalog.schema_text(tables, self.column_types)]
        if self.strategy.few_shot:
            parts.append("### Examples")
            for ex in self.example_retriever.retrieve(question)[: self.strategy.few_shot]:
                parts.append(f"Q: {ex.question}\n```sql\n{ex.sql}\n```")
        parts += ["### Question", question]
        return system, [{"role": "user", "content": "\n\n".join(parts)}], tables

    # ----------------------------------------------------------------- run
    def ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        system, messages, tables = self.build_prompt(question)
        ans = Answer(question, None, None, None, tables_used_in_prompt=tables)
        for attempt_no in range(self.strategy.max_retries + 1):
            reply = self.llm.complete(system, messages)
            ans.input_tokens += reply.input_tokens
            ans.output_tokens += reply.output_tokens
            sql = extract_sql(reply.text)
            ans.sql = sql
            if "CANNOT_ANSWER" in sql:
                ans.error = sql.split("CANNOT_ANSWER:", 1)[-1].strip() or "cannot answer"
                ans.attempts.append(Attempt(sql, ans.error))
                break
            try:
                checked = validate(sql, self.allowed, self.max_rows)
                ans.data = self.db.query(checked.limited_sql)
                ans.sql, ans.error = checked.sql, None
                ans.attempts.append(Attempt(checked.sql))
                break
            except UnsafeSQLError as e:
                # Unsafe SQL is never retried with feedback: the error could coach a jailbreak.
                ans.error = f"blocked by guardrails: {e}"
                ans.attempts.append(Attempt(sql, ans.error))
                break
            except Exception as e:  # execution error -> self-correction
                ans.error = f"{type(e).__name__}: {e}"
                ans.attempts.append(Attempt(sql, ans.error))
                if attempt_no < self.strategy.max_retries:
                    messages = messages + [
                        {"role": "assistant", "content": reply.text},
                        {"role": "user", "content": f"That query failed with this error:\n{ans.error}\n\n"
                                                    "Fix it and return the corrected query only."},
                    ]
        ans.latency_s = time.perf_counter() - t0
        ans.cost_usd = cost_usd(self.llm.model, ans.input_tokens, ans.output_tokens)
        if ans.ok:
            ans.chart = suggest_chart(ans.data)
        return ans
