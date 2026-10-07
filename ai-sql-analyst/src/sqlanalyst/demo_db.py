"""Build the demo analytics warehouse the assistant queries.

The schema mirrors the marts of the Olist warehouse project (fct_orders, dimensions,
monthly KPIs). By default it is generated from Olist-shaped synthetic data; point
``--raw-dir`` at the real Kaggle CSVs to build it from real data instead.

    python -m sqlanalyst.demo_db                      # -> data/olist.duckdb (or .sqlite)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REGIONS = {
    "AC": "North", "AL": "Northeast", "AP": "North", "AM": "North", "BA": "Northeast",
    "CE": "Northeast", "DF": "Center-West", "ES": "Southeast", "GO": "Center-West",
    "MA": "Northeast", "MT": "Center-West", "MS": "Center-West", "MG": "Southeast", "PA": "North",
    "PB": "Northeast", "PR": "South", "PE": "Northeast", "PI": "Northeast", "RJ": "Southeast",
    "RN": "Northeast", "RS": "South", "RO": "North", "RR": "North", "SC": "South",
    "SP": "Southeast", "SE": "Northeast", "TO": "North",
}
FILES = {
    "customers": "olist_customers_dataset", "orders": "olist_orders_dataset",
    "items": "olist_order_items_dataset", "payments": "olist_order_payments_dataset",
    "reviews": "olist_order_reviews_dataset", "products": "olist_products_dataset",
    "sellers": "olist_sellers_dataset", "translation": "product_category_name_translation",
}


def _raw(raw_dir: Path | None, n_orders: int, seed: int) -> dict[str, pd.DataFrame]:
    if raw_dir:
        return {k: pd.read_csv(raw_dir / f"{v}.csv") for k, v in FILES.items()}
    sys.path.insert(0, str(ROOT / "data"))
    from generate_synthetic import generate
    tables = generate(n_orders, seed)
    return {k: tables[v] for k, v in FILES.items()}


def build_tables(raw_dir: Path | None = None, n_orders: int = 20_000, seed: int = 42) -> dict[str, pd.DataFrame]:
    r = _raw(raw_dir, n_orders, seed)
    orders = r["orders"].copy()
    for c in ["order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"]:
        orders[c] = pd.to_datetime(orders[c])
    cust = r["customers"]
    orders = orders.merge(cust[["customer_id", "customer_unique_id", "customer_state", "customer_city"]],
                          on="customer_id")

    products = r["products"].merge(r["translation"], on="product_category_name", how="left")
    products["category"] = (products["product_category_name_english"]
                            .fillna(products["product_category_name"]).fillna("unknown"))
    items = r["items"].merge(products[["product_id", "category"]], on="product_id", how="left")

    basket = items.groupby("order_id").agg(
        n_items=("order_item_id", "count"), items_value=("price", "sum"),
        freight_value=("freight_value", "sum"),
        main_category=("category", "first")).reset_index()
    pay = (r["payments"].sort_values(["order_id", "payment_value"], ascending=[True, False])
           .groupby("order_id").agg(payment_type=("payment_type", "first"),
                                    installments=("payment_installments", "max")).reset_index())
    rev = (r["reviews"].sort_values("review_creation_date")
           .groupby("order_id").agg(review_score=("review_score", "last")).reset_index())

    f = (orders.merge(basket, on="order_id", how="left").merge(pay, on="order_id", how="left")
         .merge(rev, on="order_id", how="left"))
    f[["n_items", "items_value", "freight_value"]] = f[["n_items", "items_value", "freight_value"]].fillna(0)
    delivered = f["order_delivered_customer_date"]
    fct_orders = pd.DataFrame({
        "order_id": f["order_id"],
        "customer_unique_id": f["customer_unique_id"],
        "customer_state": f["customer_state"],
        "order_status": f["order_status"],
        "order_date": f["order_purchase_timestamp"].dt.strftime("%Y-%m-%d"),
        "order_year": f["order_purchase_timestamp"].dt.year,
        "order_month": f["order_purchase_timestamp"].dt.strftime("%Y-%m"),
        "n_items": f["n_items"].astype(int),
        "items_value": f["items_value"].round(2),
        "freight_value": f["freight_value"].round(2),
        "order_value": (f["items_value"] + f["freight_value"]).round(2),
        "payment_type": f["payment_type"],
        "installments": f["installments"],
        "review_score": f["review_score"],
        "delivery_days": (delivered.dt.normalize() - f["order_purchase_timestamp"].dt.normalize()).dt.days,
        "delay_days": (delivered.dt.normalize() - f["order_estimated_delivery_date"].dt.normalize()).dt.days,
        "is_late": np.where(delivered.isna(), np.nan,
                            (delivered.dt.normalize() > f["order_estimated_delivery_date"].dt.normalize()).astype(float)),
        "is_canceled": f["order_status"].isin(["canceled", "unavailable"]).astype(int),
        "main_category": f["main_category"],
    })
    fct_orders["order_seq"] = (fct_orders.sort_values(["order_date", "order_id"])
                               .groupby("customer_unique_id").cumcount() + 1)

    first = fct_orders.sort_values("order_seq").groupby("customer_unique_id").first()
    agg = fct_orders.groupby("customer_unique_id").agg(
        n_orders=("order_id", "count"),
        lifetime_value=("order_value", lambda s: s[fct_orders.loc[s.index, "is_canceled"] == 0].sum()))
    dim_customers = pd.DataFrame({
        "customer_unique_id": first.index,
        "state_code": first["customer_state"].values,
        "region": first["customer_state"].map(REGIONS).values,
        "first_order_date": first["order_date"].values,
        "n_orders": agg.loc[first.index, "n_orders"].values,
        "lifetime_value": agg.loc[first.index, "lifetime_value"].round(2).values,
    })
    dim_customers["is_repeat_customer"] = (dim_customers["n_orders"] > 1).astype(int)

    dim_products = products[["product_id", "category", "product_weight_g", "product_photos_qty"]].rename(
        columns={"product_weight_g": "weight_g", "product_photos_qty": "photos_qty"})
    sellers = r["sellers"]
    dim_sellers = pd.DataFrame({"seller_id": sellers["seller_id"], "state_code": sellers["seller_state"],
                                "region": sellers["seller_state"].map(REGIONS), "city": sellers["seller_city"]})
    fct_order_items = items.merge(fct_orders[["order_id", "order_date", "is_canceled"]], on="order_id")[
        ["order_id", "order_item_id", "product_id", "seller_id", "category", "price", "freight_value",
         "order_date", "is_canceled"]].rename(columns={"order_item_id": "item_seq"})

    valid = fct_orders[fct_orders["is_canceled"] == 0]
    m = fct_orders.groupby("order_month").agg(orders=("order_id", "count"),
                                              new_customers=("order_seq", lambda s: int((s == 1).sum())),
                                              avg_review_score=("review_score", "mean"),
                                              late_delivery_rate=("is_late", "mean"))
    m["revenue"] = valid.groupby("order_month")["order_value"].sum()
    m["avg_order_value"] = m["revenue"] / valid.groupby("order_month").size()
    mart_monthly_kpis = m.reset_index().round(4)[["order_month", "orders", "revenue", "avg_order_value",
                                                  "new_customers", "avg_review_score", "late_delivery_rate"]]
    return {"fct_orders": fct_orders, "fct_order_items": fct_order_items, "dim_customers": dim_customers,
            "dim_products": dim_products, "dim_sellers": dim_sellers, "mart_monthly_kpis": mart_monthly_kpis}


def write_db(tables: dict[str, pd.DataFrame], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".duckdb":
        import duckdb
        path.unlink(missing_ok=True)
        con = duckdb.connect(str(path))
        for name, df in tables.items():
            con.register("df_tmp", df)
            con.execute(f"create table {name} as select * from df_tmp")
            con.unregister("df_tmp")
        con.execute("alter table fct_orders alter order_date type date")
        con.execute("alter table fct_order_items alter order_date type date")
        con.execute("alter table dim_customers alter first_order_date type date")
        con.close()
    else:
        path.unlink(missing_ok=True)
        con = sqlite3.connect(path)
        for name, df in tables.items():
            df.to_sql(name, con, index=False)
        con.close()
    return path


def default_db_path() -> Path:
    try:
        import duckdb  # noqa: F401
        return ROOT / "data" / "olist.duckdb"
    except ImportError:
        return ROOT / "data" / "olist.sqlite"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", help="folder with the real Olist CSVs from Kaggle")
    ap.add_argument("--out", default=str(default_db_path()))
    ap.add_argument("--orders", type=int, default=20_000)
    args = ap.parse_args()
    t = build_tables(Path(args.raw_dir) if args.raw_dir else None, args.orders)
    p = write_db(t, Path(args.out))
    print(f"wrote {p}: " + ", ".join(f"{k} ({len(v):,})" for k, v in t.items()))
