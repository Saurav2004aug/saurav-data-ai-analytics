"""Dagster orchestration: ingest -> dbt build (models + tests) -> insights report.

    dagster dev -f orchestration/definitions.py      # UI at http://localhost:3000

Every dbt model becomes a Dagster asset with lineage back to the raw tables, and every
dbt test becomes an asset check, so a failing data test is visible on the asset graph.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Definitions,
    MaterializeResult,
    ScheduleDefinition,
    asset,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))
from ingest import TABLES, load  # noqa: E402

dbt_project = DbtProject(project_dir=ROOT / "dbt", profiles_dir=ROOT / "dbt")
dbt_project.prepare_if_dev()  # compiles the manifest when running `dagster dev`


# Raw tables. Keys match dbt's source('olist', <table>) so lineage connects automatically.
@multi_asset(
    specs=[AssetSpec(AssetKey(["olist", t]), group_name="raw", kinds={"duckdb"})
           for t in TABLES.values()],
)
def olist_raw_tables(context: AssetExecutionContext):
    counts = load()
    for table, n in counts.items():
        yield MaterializeResult(asset_key=AssetKey(["olist", table]), metadata={"row_count": n})


@dbt_assets(manifest=dbt_project.manifest_path)
def olist_dbt_models(context: AssetExecutionContext, dbt: DbtCliResource):
    # `build` = seeds + models + tests in DAG order; failing tests surface as asset checks
    yield from dbt.cli(["build"], context=context).stream()


@asset(deps=[AssetKey(["mart_monthly_kpis"]), AssetKey(["mart_delivery_performance"]),
             AssetKey(["mart_cohort_retention"]), AssetKey(["mart_customer_rfm"])],
       group_name="reporting", kinds={"python"})
def insights_report() -> MaterializeResult:
    subprocess.run([sys.executable, str(ROOT / "analysis" / "insights_report.py")], check=True)
    return MaterializeResult(metadata={"path": str(ROOT / "reports" / "insights.md")})


daily_refresh = ScheduleDefinition(
    name="daily_refresh",
    job=define_asset_job("full_refresh_job", selection="*"),
    cron_schedule="0 6 * * *",          # 06:00 every day
    execution_timezone="Asia/Kolkata",
)

defs = Definitions(
    assets=[olist_raw_tables, olist_dbt_models, insights_report],
    schedules=[daily_refresh],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
