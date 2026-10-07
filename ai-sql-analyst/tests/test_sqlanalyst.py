"""Tests: guardrails, result comparison, retrieval, and the agent loop (scripted LLM)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlanalyst.agent import SQLAgent  # noqa: E402
from sqlanalyst.catalog import Catalog, SchemaRetriever, tables_in_sql  # noqa: E402
from sqlanalyst.charts import suggest_chart  # noqa: E402
from sqlanalyst.db import Database, QueryTimeout  # noqa: E402
from sqlanalyst.demo_db import build_tables, write_db  # noqa: E402
from sqlanalyst.evaluate import load_benchmark, results_match, results_match_relaxed, run  # noqa: E402
from sqlanalyst.guardrails import UnknownTableError, UnsafeSQLError, extract_sql, validate  # noqa: E402
from sqlanalyst.llm import ScriptedLLM  # noqa: E402

ALLOWED = {"fct_orders", "fct_order_items", "dim_customers", "dim_products", "dim_sellers", "mart_monthly_kpis"}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "olist.sqlite"
    write_db(build_tables(n_orders=4000, seed=1), path)
    return Database(path)


# ----------------------------------------------------------------- guardrails
@pytest.mark.parametrize("sql", [
    "DROP TABLE fct_orders",
    "SELECT 1; DELETE FROM fct_orders",
    "WITH x AS (SELECT 1) DELETE FROM fct_orders",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM '/etc/passwd'",
    "ATTACH 'other.db' AS o",
    "PRAGMA table_info(fct_orders)",
    "INSTALL httpfs",
    "SELECT * FROM fct_orders; ",  # fine on its own...
])
def test_guardrails_block_unsafe(sql):
    if sql.strip().rstrip(";").strip() == "SELECT * FROM fct_orders":
        validate(sql, ALLOWED)             # ...a single trailing semicolon is allowed
        return
    with pytest.raises(UnsafeSQLError):
        validate(sql, ALLOWED)


def test_guardrails_allow_normal_queries_and_strings_with_keywords():
    v = validate("-- top states\nSELECT customer_state, COUNT(*) FROM fct_orders "
                 "WHERE payment_type <> 'drop; delete' GROUP BY 1;", ALLOWED, max_rows=50)
    assert v.limited_sql.endswith("LIMIT 50")
    validate("SELECT EXTRACT(year FROM order_date) FROM fct_orders", ALLOWED)


def test_unknown_table_is_retryable_error_not_security_error():
    with pytest.raises(UnknownTableError):
        validate("SELECT * FROM users", ALLOWED)


def test_extract_sql_from_llm_reply():
    assert extract_sql("Sure!\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"
    assert extract_sql("SELECT 2") == "SELECT 2"


def test_tables_in_sql_ignores_ctes():
    sql = "WITH m AS (SELECT * FROM fct_orders) SELECT * FROM m JOIN dim_customers c ON 1=1"
    assert tables_in_sql(sql) == {"fct_orders", "dim_customers"}


# ----------------------------------------------------------------- comparison
def test_results_match_ignores_column_order_and_float_noise():
    gold = pd.DataFrame({"state": ["SP", "RJ"], "revenue": [10.004, 5.0]})
    pred = pd.DataFrame({"rev": [5.0, 10.0], "s": ["RJ", "SP"]})
    assert results_match(pred, gold, ordered=False)
    assert not results_match(pred, gold, ordered=True)
    assert not results_match(pred.assign(rev=[5.0, 11.0]), gold)


def test_relaxed_match_allows_extra_columns():
    gold = pd.DataFrame({"state": ["SP", "RJ"]})
    pred = pd.DataFrame({"state": ["SP", "RJ"], "n": [3, 2]})
    assert not results_match(pred, gold) and results_match_relaxed(pred, gold)


# ----------------------------------------------------------------- retrieval
def test_schema_retrieval_recall_at_3():
    r = SchemaRetriever(Catalog(), k=3)
    items = load_benchmark()
    hits = [tables_in_sql(it.sql) <= set(r.retrieve(it.question)) for it in items]
    assert sum(hits) / len(hits) >= 0.95


def test_every_gold_query_runs(db):
    for it in load_benchmark():
        db.query(it.sql)


# ----------------------------------------------------------------- agent loop
def test_agent_self_corrects_execution_error(db):
    llm = ScriptedLLM(["```sql\nSELECT COUNT(*) AS n FROM fct_orders WHERE no_such_col = 1\n```",
                       "```sql\nSELECT COUNT(*) AS n FROM fct_orders\n```"])
    ans = SQLAgent(llm, db, strategy="full").ask("How many orders?")
    assert ans.ok and len(ans.attempts) == 2 and ans.data.iloc[0, 0] == 4000
    assert "no_such_col" in llm.calls[1][1][-1]["content"]      # error was fed back


def test_agent_never_executes_or_retries_unsafe_sql(db):
    llm = ScriptedLLM(["```sql\nDROP TABLE fct_orders\n```", "```sql\nSELECT 1\n```"])
    ans = SQLAgent(llm, db, strategy="full").ask("delete everything")
    assert not ans.ok and "guardrails" in ans.error and len(llm.calls) == 1
    assert db.query("SELECT COUNT(*) FROM fct_orders").iloc[0, 0] == 4000


def test_agent_cannot_answer(db):
    llm = ScriptedLLM(["```sql\n-- CANNOT_ANSWER: no marketing spend data\n```"])
    ans = SQLAgent(llm, db).ask("What is our ROAS on Google Ads?")
    assert not ans.ok and "marketing" in ans.error


def test_prompt_contains_business_rules_and_retrieved_schema(db):
    llm = ScriptedLLM(["```sql\nSELECT 1\n```"])
    SQLAgent(llm, db, strategy="retrieval_fewshot").ask("Top sellers by revenue")
    system, messages = llm.calls[0]
    assert "is_canceled = 0" in system
    assert "dim_sellers" in messages[0]["content"] and "### Examples" in messages[0]["content"]


def test_database_is_read_only_and_times_out(db):
    with pytest.raises(Exception):
        db.con.execute("DELETE FROM fct_orders")
    db.timeout_s = 0.05
    with pytest.raises(QueryTimeout):
        db.query("WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT COUNT(*) FROM r")
    db.timeout_s = 15


def test_chart_suggestion():
    assert suggest_chart(pd.DataFrame({"order_month": ["2018-01", "2018-02"], "revenue": [1, 2]}))["type"] == "line"
    assert suggest_chart(pd.DataFrame({"state": ["SP", "RJ"], "revenue": [1, 2]}))["type"] == "bar"
    assert suggest_chart(pd.DataFrame({"n": [5]})) is None


# ----------------------------------------------------------------- harness
def test_harness_oracle_scores_100_percent(db):
    df = run(["full"], llm_kind="oracle", db_path=str(db.path))
    assert df["correct"].all()


def test_harness_detects_wrong_answers_and_counts_retries(db):
    df = run(["full"], llm_kind="noisy-oracle", db_path=str(db.path), seed=3)
    assert 0.5 < df["correct"].mean() < 1.0
    assert df["recovered_by_retry"].sum() >= 1
