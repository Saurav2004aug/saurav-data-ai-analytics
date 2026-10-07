"""Load the Olist CSVs into the DuckDB warehouse (schema ``raw``).

    python ingestion/ingest.py --download        # fetch from Kaggle, then load
    python ingestion/ingest.py                   # load CSVs already in data/raw

Kaggle download needs a token in ~/.kaggle/kaggle.json (kaggle.com -> Settings -> API).
Every load is recorded in ``raw._load_audit`` (file, rows, checksum, timestamp) so you
can always answer "which data is this dashboard built on?".
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "warehouse" / "olist.duckdb"

# CSV file stem -> raw table name
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


def download(raw_dir: Path = RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "datasets", "download", "-d", "olistbr/brazilian-ecommerce",
                    "-p", str(raw_dir)], check=True)
    with zipfile.ZipFile(raw_dir / "brazilian-ecommerce.zip") as z:
        z.extractall(raw_dir)


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(raw_dir: Path = RAW_DIR, db_path: Path = DB_PATH) -> dict[str, int]:
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("create schema if not exists raw")
    con.execute("""create table if not exists raw._load_audit (
        table_name varchar, source_file varchar, row_count bigint, md5 varchar,
        loaded_at timestamptz)""")
    counts = {}
    for stem, table in TABLES.items():
        path = raw_dir / f"{stem}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run with --download or generate synthetic data")
        # all_varchar: keep raw exactly as delivered; typing happens in dbt staging models
        con.execute(f"""create or replace table raw.{table} as
                        select * from read_csv('{path.as_posix()}', header=true, all_varchar=true)""")
        n = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        con.execute("insert into raw._load_audit values (?, ?, ?, ?, ?)",
                    [table, path.name, n, md5(path), datetime.now(timezone.utc)])
        counts[table] = n
        print(f"raw.{table:22s} {n:>9,} rows")
    con.close()
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="download from Kaggle first")
    ap.add_argument("--raw-dir", default=str(RAW_DIR))
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    if args.download:
        download(Path(args.raw_dir))
    load(Path(args.raw_dir), Path(args.db))
