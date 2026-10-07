"""Benchmark harness: execution accuracy of text-to-SQL strategies.

    python -m sqlanalyst.evaluate --strategies zero_shot retrieval retrieval_fewshot full
    python -m sqlanalyst.evaluate --llm oracle          # harness self-check, no API key needed

Scoring
-------
* **Execution accuracy (EX)**: the predicted query's result equals the gold result.
  Column order and names are ignored, numbers are compared at 2 decimals, and row order
  only matters when the benchmark item is marked ``ordered``.
* **Relaxed EX**: every gold column appears in the prediction (extra columns allowed), a
  common real-world tolerance ("also showed the count").
* **Table recall**: were all tables the gold query needs included in the prompt? This
  isolates *retrieval* failures from *generation* failures.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from .agent import STRATEGIES, SQLAgent
from .catalog import Catalog, SchemaRetriever, tables_in_sql
from .db import Database
from .llm import AnthropicLLM, ScriptedLLM

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmark" / "questions.yml"


@dataclass
class Item:
    id: str
    difficulty: str
    question: str
    sql: str
    ordered: bool = False


def load_benchmark(path: Path = BENCH) -> list[Item]:
    return [Item(q["id"], q["difficulty"], q["question"], q["sql"].strip(), q.get("ordered", False))
            for q in yaml.safe_load(path.read_text())]


# --------------------------------------------------------------------------- #
# Result comparison
# --------------------------------------------------------------------------- #
def _norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return round(float(v), 2) + 0.0          # +0.0 turns -0.0 into 0.0
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10] if len(v.isoformat()) >= 10 else v.isoformat()
    return str(v)


def _key(x):
    return (x is None, str(type(x)), x if x is not None else 0)


def _rows(df: pd.DataFrame) -> list[tuple]:
    return [tuple(sorted((_norm(v) for v in row), key=_key)) for row in df.itertuples(index=False)]


def results_match(pred: pd.DataFrame, gold: pd.DataFrame, ordered: bool = False) -> bool:
    if pred is None or pred.shape != gold.shape:
        return False
    p, g = _rows(pred), _rows(gold)
    return p == g if ordered else sorted(p, key=repr) == sorted(g, key=repr)


def results_match_relaxed(pred: pd.DataFrame, gold: pd.DataFrame) -> bool:
    if pred is None or len(pred) != len(gold) or pred.shape[1] < gold.shape[1]:
        return False
    pred_cols = [sorted((_norm(v) for v in pred[c]), key=_key) for c in pred.columns]
    return all(sorted((_norm(v) for v in gold[c]), key=_key) in pred_cols for c in gold.columns)


# --------------------------------------------------------------------------- #
# Offline "models" that validate the harness itself (no API key)
# --------------------------------------------------------------------------- #
PERTURBATIONS = [
    (r"is_canceled\s*=\s*0", "1 = 1"),                  # forgets the revenue definition
    (r"\bDESC\b", "ASC"),                               # wrong sort direction
    (r"\bAVG\(", "SUM("),                              # wrong aggregation
    (r"\bFROM fct_orders\b", "FROM fct_order"),         # typo -> execution error -> self-correction
]


def noisy_oracle_replies(item: Item, rng: random.Random, p_error: float = 0.35) -> list[str]:
    """Gold SQL, sometimes corrupted. If corrupted, the 'retry' reply is the fixed gold SQL,
    so the harness can show that self-correction recovers execution errors (and only those)."""
    sql = item.sql
    if rng.random() < p_error:
        pattern, repl = rng.choice(PERTURBATIONS)
        bad = re.sub(pattern, repl, sql, count=1, flags=re.IGNORECASE)
        if bad != sql:
            return [f"```sql\n{bad}\n```", f"```sql\n{sql}\n```"]
    return [f"```sql\n{sql}\n```"]


# --------------------------------------------------------------------------- #
def run(strategies: list[str], llm_kind: str = "anthropic", model: str | None = None,
        db_path: str | None = None, limit: int | None = None, seed: int = 0) -> pd.DataFrame:
    db = Database(db_path)
    catalog = Catalog()
    items = load_benchmark()[:limit] if limit else load_benchmark()
    gold = {it.id: db.query(it.sql) for it in items}
    rows = []
    for strat in strategies:
        rng = random.Random(seed)
        shared_llm = AnthropicLLM(model) if llm_kind == "anthropic" else None
        for it in items:
            if llm_kind == "anthropic":
                llm = shared_llm
            elif llm_kind == "oracle":
                llm = ScriptedLLM([f"```sql\n{it.sql}\n```"])
            else:
                llm = ScriptedLLM(noisy_oracle_replies(it, rng))
            agent = SQLAgent(llm, db, catalog, strategy=strat)
            ans = agent.ask(it.question)
            need = tables_in_sql(it.sql)
            rows.append({
                "id": it.id, "difficulty": it.difficulty, "strategy": strat, "question": it.question,
                "correct": ans.ok and results_match(ans.data, gold[it.id], it.ordered),
                "relaxed": ans.ok and results_match_relaxed(ans.data, gold[it.id]),
                "executed": ans.ok, "attempts": len(ans.attempts),
                "recovered_by_retry": ans.ok and len(ans.attempts) > 1,
                "table_recall": need <= set(ans.tables_used_in_prompt),
                "error": ans.error, "pred_sql": ans.sql, "gold_sql": it.sql,
                "input_tokens": ans.input_tokens, "output_tokens": ans.output_tokens,
                "latency_s": round(ans.latency_s, 3), "cost_usd": ans.cost_usd,
            })
            if llm_kind == "anthropic":
                time.sleep(0.2)          # stay polite with rate limits
    return pd.DataFrame(rows)


def retrieval_recall(k_values=(1, 2, 3, 4)) -> pd.DataFrame:
    """Table recall@k of the schema retriever alone (no LLM involved)."""
    catalog = Catalog()
    items = load_benchmark()
    out = []
    for k in k_values:
        r = SchemaRetriever(catalog, k=k)
        hits = [tables_in_sql(it.sql) <= set(r.retrieve(it.question)) for it in items]
        out.append({"k": k, "table_recall": sum(hits) / len(hits)})
    return pd.DataFrame(out)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("strategy", sort=False)
    s = pd.DataFrame({
        "EX": g["correct"].mean(), "relaxed_EX": g["relaxed"].mean(),
        "valid_SQL": g["executed"].mean(), "table_recall": g["table_recall"].mean(),
        "recovered_by_retry": g["recovered_by_retry"].sum(),
        "avg_input_tokens": g["input_tokens"].mean().round(0),
        "avg_latency_s": g["latency_s"].mean().round(2), "total_cost_usd": g["cost_usd"].sum().round(4),
    })
    by_diff = df.pivot_table(index="strategy", columns="difficulty", values="correct", aggfunc="mean", sort=False)
    return s.join(by_diff.add_prefix("EX_"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", nargs="+", default=list(STRATEGIES))
    ap.add_argument("--llm", choices=["anthropic", "oracle", "noisy-oracle"], default="anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "reports"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = run(args.strategies, args.llm, args.model, args.db, args.limit)
    summary = summarize(df)
    rec = retrieval_recall()
    tag = args.llm if args.llm != "anthropic" else (args.model or "claude")
    df.to_csv(out / f"eval_{tag}_details.csv", index=False)
    summary.to_csv(out / f"eval_{tag}_summary.csv")
    (out / f"eval_{tag}_summary.json").write_text(json.dumps(
        {"summary": summary.reset_index().to_dict(orient="records"),
         "retrieval_recall": rec.to_dict(orient="records")}, indent=2, default=float))
    pd.set_option("display.width", 200)
    print(summary.to_string(float_format=lambda v: f"{v:.3f}"))
    print("\nSchema retrieval (no LLM):\n" + rec.to_string(index=False))
    fails = df[~df["correct"]][["strategy", "id", "difficulty", "error"]]
    if len(fails):
        print(f"\n{len(fails)} incorrect answers -> see {out / f'eval_{tag}_details.csv'}")


if __name__ == "__main__":
    main()
