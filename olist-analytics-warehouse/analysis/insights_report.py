"""Business insights report built from the warehouse marts.

Reads the DuckDB warehouse produced by `dbt build` (or, if DuckDB isn't available,
the SQLite build from tests/dbt_sqlite_harness.py) and writes charts + a Markdown
summary with the headline numbers to reports/.

    python analysis/insights_report.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DUCKDB = ROOT / "warehouse" / "olist.duckdb"
SQLITE = ROOT / "warehouse" / "olist_harness.sqlite"
OUT = ROOT / "reports"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
SEQ = LinearSegmentedColormap.from_list("seq", ["#eef4fc", "#9cc2ef", BLUE, "#123f78"])
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "figure.dpi": 130,
})


class Warehouse:
    def __init__(self):
        if DUCKDB.exists():
            try:
                import duckdb
                self.con, self.kind = duckdb.connect(str(DUCKDB), read_only=True), "duckdb"
                return
            except ImportError:
                pass
        if not SQLITE.exists():
            raise SystemExit("No warehouse found. Run `make build` (dbt) or `make harness` first.")
        self.con, self.kind = sqlite3.connect(SQLITE), "sqlite"

    def table(self, name: str) -> pd.DataFrame:
        if self.kind == "duckdb":
            schema = "main_analytics" if name.startswith("mart_") else "main_core"
            return self.con.execute(f"select * from {schema}.{name}").df()
        return pd.read_sql_query(f"select * from {name}", self.con)


def save(fig, name: str) -> str:
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / "figures" / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}.png"


def main() -> None:
    wh = Warehouse()
    kpis = wh.table("mart_monthly_kpis")
    kpis["order_month"] = pd.to_datetime(kpis["order_month"])
    kpis = kpis.sort_values("order_month")
    full = kpis[kpis["orders"] >= 50]  # skip the sparse launch months
    delivery = wh.table("mart_delivery_performance").sort_values("delay_bucket")
    cohorts = wh.table("mart_cohort_retention")
    rfm = wh.table("mart_customer_rfm")
    states = wh.table("mart_state_performance")
    cats = wh.table("mart_category_performance").sort_values("revenue", ascending=False)
    figs = []

    # 1. Revenue trend
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(full["order_month"], full["revenue"] / 1e3, color=BLUE, linewidth=2, marker="o", markersize=4)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"R${v:,.0f}k"))
    ax.set_title("Monthly revenue (non-canceled orders)")
    figs.append(save(fig, "01_revenue_trend"))

    # 2. Delivery delay -> review score
    fig, ax = plt.subplots(figsize=(8, 3.8))
    labels = delivery["delay_bucket"].str[3:]
    colors = [ORANGE if "late" in b else BLUE for b in delivery["delay_bucket"]]
    ax.bar(labels, delivery["avg_review_score"], color=colors, width=0.7)
    for i, v in enumerate(delivery["avg_review_score"]):
        ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=9, color=INK_2)
    ax.set_ylim(0, 5.3)
    ax.set_ylabel("Average review score")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="x", visible=False)
    ax.set_title("Late deliveries destroy satisfaction")
    figs.append(save(fig, "02_delivery_vs_review"))

    # 3. Cohort retention heatmap (months 1-6, cohorts with >= 100 customers)
    piv = (cohorts[(cohorts["months_since_first"].between(1, 6)) & (cohorts["cohort_customers"] >= 100)]
           .pivot_table(index="cohort_month", columns="months_since_first", values="retention_rate"))
    fig, ax = plt.subplots(figsize=(7, 0.32 * len(piv) + 1.4))
    im = ax.imshow(piv.values, cmap=SEQ, aspect="auto", vmin=0)
    ax.set_xticks(range(piv.shape[1]), [f"M{c}" for c in piv.columns])
    ax.set_yticks(range(len(piv)), [str(i)[:7] for i in piv.index])
    ax.grid(False)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1%}", ha="center", va="center", fontsize=7,
                        color="white" if v > np.nanmax(piv.values) * 0.6 else INK)
    fig.colorbar(im, ax=ax, fraction=0.04, format=PercentFormatter(1, 1))
    ax.set_title("Repeat-purchase retention by monthly cohort")
    figs.append(save(fig, "03_cohort_retention"))

    # 4. RFM segments
    seg = rfm.groupby("segment").agg(customers=("customer_unique_id", "count"),
                                     revenue=("monetary", "sum")).sort_values("revenue")
    seg["revenue_share"] = seg["revenue"] / seg["revenue"].sum()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.barh(seg.index, seg["revenue_share"], color=BLUE, height=0.6)
    for i, (share, n) in enumerate(zip(seg["revenue_share"], seg["customers"])):
        ax.text(share + 0.004, i, f"{share:.0%}  ({n:,} customers)", va="center", fontsize=9, color=INK_2)
    ax.xaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.set_xlim(0, seg["revenue_share"].max() * 1.45)
    ax.grid(axis="y", visible=False)
    ax.set_title("Revenue share by RFM segment")
    figs.append(save(fig, "04_rfm_segments"))

    # 5. Delivery time by state
    st = states[states["orders"] >= 30].sort_values("avg_delivery_days")
    fig, ax = plt.subplots(figsize=(8, 0.26 * len(st) + 1.2))
    ax.barh(st["state_code"], st["avg_delivery_days"], color=BLUE, height=0.65)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Average days from purchase to delivery")
    ax.set_title("Delivery time by customer state")
    figs.append(save(fig, "05_delivery_by_state"))

    # ---- summary numbers -------------------------------------------------------
    late = delivery[delivery["delay_bucket"].str.contains("late")]
    ontime = delivery[~delivery["delay_bucket"].str.contains("late")]
    w_avg = lambda d: (d["avg_review_score"] * d["orders"]).sum() / d["orders"].sum()  # noqa: E731
    one_star = lambda d: (d["one_star_rate"] * d["orders"]).sum() / d["orders"].sum()  # noqa: E731
    m1 = cohorts[cohorts["months_since_first"] == 1]
    m1_ret = (m1["active_customers"].sum() / m1["cohort_customers"].sum()) if len(m1) else float("nan")
    repeat_share = (rfm["frequency"] > 1).mean()
    top_cats = cats.head(3)
    last12 = kpis.tail(12)
    summary = f"""# Olist marketplace: insights report

_Built from the `{wh.kind}` warehouse. Every number below comes from the dbt marts._

## Headline findings
1. **Delivery is the #1 driver of satisfaction.** Late orders average **{w_avg(late):.2f}★** vs **{w_avg(ontime):.2f}★** for on-time orders, and **{one_star(late):.0%}** of late orders get 1★ (vs {one_star(ontime):.0%}).
2. **Retention is the growth gap.** Only **{repeat_share:.1%}** of customers ever order twice; month-1 retention is **{m1_ret:.2%}**. Growth is almost entirely acquisition-driven.
3. **Revenue concentration.** The top 3 categories ({", ".join(top_cats["category"])}) generate **{top_cats["revenue_share"].sum():.0%}** of revenue.
4. **Geography matters.** Delivery takes **{st["avg_delivery_days"].min():.0f}** days in the fastest state ({st.iloc[0]["state_code"]}) vs **{st["avg_delivery_days"].max():.0f}** in the slowest ({st.iloc[-1]["state_code"]}).
5. **Last 12 months:** revenue R${last12["revenue"].sum()/1e6:,.2f}M, {last12["valid_orders"].sum():,} orders, AOV R${last12["revenue"].sum()/last12["valid_orders"].sum():,.0f}, late-delivery rate {last12["late_delivery_rate"].mean():.1%}.

## Recommendations
- Tighten delivery estimates / carrier SLAs for the slowest states: every late order costs roughly {w_avg(ontime) - w_avg(late):.1f} review stars.
- Launch a second-purchase programme (post-delivery voucher, category cross-sell) aimed at "Recent one-timers" and "Promising big spenders".
- Put "Needs attention" sellers from `mart_seller_scorecard` on a shipping-time improvement plan.

## Charts
""" + "\n".join(f"![]({f})" for f in figs) + "\n"
    (OUT / "insights.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
