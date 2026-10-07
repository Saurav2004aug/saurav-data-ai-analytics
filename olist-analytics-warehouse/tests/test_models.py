"""Model logic tests. Builds the full dbt project on SQLite from synthetic data.

    pytest -q
"""
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ingestion"))

from dbt_sqlite_harness import SqliteDbt  # noqa: E402
from generate_synthetic import generate  # noqa: E402


def _write(tables: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
    return out


@pytest.fixture(scope="module")
def raw_dir(tmp_path_factory):
    return _write(generate(n_orders=6000, seed=3), tmp_path_factory.mktemp("raw"))


@pytest.fixture(scope="module")
def wh(raw_dir):
    dbt = SqliteDbt()
    result = dbt.build(raw_dir)
    return dbt, result


def test_all_models_build_and_all_data_tests_pass(wh):
    _, result = wh
    assert len(result.models) >= 20
    assert not result.failed, [t.name for t in result.failed]


def test_fct_orders_grain_matches_source(wh, raw_dir):
    dbt, _ = wh
    n_src = len(pd.read_csv(raw_dir / "olist_orders_dataset.csv"))
    n_fct = dbt.query("select count(*) n, count(distinct order_id) d from fct_orders").iloc[0]
    assert n_fct["n"] == n_fct["d"] == n_src


def test_customer_dimension_uses_unique_id(wh, raw_dir):
    dbt, _ = wh
    cust = pd.read_csv(raw_dir / "olist_customers_dataset.csv")
    n_dim = dbt.query("select count(*) n from dim_customers").iloc[0, 0]
    assert n_dim == cust["customer_unique_id"].nunique() < len(cust)


def test_order_value_matches_python(wh, raw_dir):
    """Independent re-computation of total revenue in pandas."""
    dbt, _ = wh
    items = pd.read_csv(raw_dir / "olist_order_items_dataset.csv")
    orders = pd.read_csv(raw_dir / "olist_orders_dataset.csv")
    valid = orders.loc[~orders["order_status"].isin(["canceled", "unavailable"]), "order_id"]
    expected = items[items["order_id"].isin(valid)][["price", "freight_value"]].sum().sum()
    got = dbt.query("select sum(revenue) r from mart_monthly_kpis").iloc[0, 0]
    assert got == pytest.approx(expected, rel=1e-9)


def test_late_deliveries_get_worse_reviews(wh):
    dbt, _ = wh
    d = dbt.query("select * from mart_delivery_performance")
    late = d[d["delay_bucket"].str.contains("late")]
    early = d[d["delay_bucket"].str.contains("early")]
    assert late["avg_review_score"].max() < early["avg_review_score"].min()


def test_latest_review_wins_when_duplicated(wh):
    dbt, _ = wh
    dup = dbt.query("""
        select r.order_id, max(r.created_at) latest
        from stg_olist__reviews r group by r.order_id having count(*) > 1""")
    assert len(dup) > 0
    joined = dbt.query("select order_id, reviewed_at from int_order_reviews").set_index("order_id")
    assert (joined.loc[dup["order_id"], "reviewed_at"].values == dup["latest"].values).all()


def test_rfm_scores_in_range(wh):
    dbt, _ = wh
    r = dbt.query("select min(r_score) a, max(r_score) b, min(m_score) c, max(m_score) d from mart_customer_rfm")
    assert tuple(r.iloc[0]) == (1, 5, 1, 5)


def test_data_tests_catch_bad_data(raw_dir, tmp_path):
    """Corrupt the raw data and make sure the test suite notices."""
    bad = tmp_path / "bad"
    shutil.copytree(raw_dir, bad)
    items = pd.read_csv(bad / "olist_order_items_dataset.csv")
    items.loc[0, "price"] = -10                                   # negative price
    items.to_csv(bad / "olist_order_items_dataset.csv", index=False)
    orders = pd.read_csv(bad / "olist_orders_dataset.csv")
    orders = pd.concat([orders, orders.head(1)])                  # duplicate order_id
    orders.to_csv(bad / "olist_orders_dataset.csv", index=False)

    result = SqliteDbt().build(bad)
    failed = {t.name for t in result.failed}
    assert "non_negative:stg_olist__order_items.price" in failed
    assert "unique:stg_olist__orders.order_id" in failed
