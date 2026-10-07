"""Offline backtest: run the full analytics pipeline on simulated market data and report
what it found against the planted ground truth.

    python scripts/offline_report.py --minutes 120
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from cryptostream.pipeline import MemorySink, Pipeline, evaluate_alerts  # noqa: E402
from cryptostream.simulator import DEFAULT_SYMBOLS, simulate  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "figure.dpi": 130,
})


def to_dt(ts):
    return pd.to_datetime(ts, unit="s", utc=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    out = ROOT / "reports"
    (out / "figures").mkdir(parents=True, exist_ok=True)

    trades, events = simulate(duration_s=args.minutes * 60, seed=args.seed)
    sink = MemorySink()
    stats = Pipeline([sink]).run(trades)
    ev = evaluate_alerts(sink.alerts, events)

    m = pd.DataFrame([asdict(x) for x in sink.metrics])
    m["time"] = to_dt(m["ts"])
    alerts = pd.DataFrame([asdict(a) for a in sink.alerts])
    alerts["time"] = to_dt(alerts["ts"])

    # 1. Price, VWAP, alerts (BTC)
    sym = "BTCUSDT"
    b = m[m["symbol"] == sym]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(b["time"], b["close"], color=BLUE, linewidth=1.2, label="Price")
    ax.plot(b["time"], b["vwap_5m"], color=ORANGE, linewidth=1.6, label="5-min VWAP")
    for e in (e for e in events if e.symbol == sym):
        ax.axvline(to_dt(e.ts), color=GRID, linewidth=6, zorder=0)
    a = alerts[alerts["symbol"] == sym].merge(b[["ts", "close"]], on="ts")
    # one marker per alerted second, shaped by the strongest detector that fired
    marks = {"isolation_forest": ("D", 40, "Isolation-forest only"),
             "volume_burst": ("o", 50, "Volume-burst alert"),
             "price_jump": ("v", 90, "Price-jump alert")}
    shown = set()
    for kind, (mk, size, label) in reversed(list(marks.items())):
        k = a[(a["kind"] == kind) & ~a["ts"].isin(shown)]
        shown |= set(k["ts"])
        if len(k):
            ax.scatter(k["time"], k["close"], marker=mk, s=size, color=INK, zorder=5,
                       edgecolor=SURFACE, linewidth=1.5, label=label)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("USDT")
    ax.legend(loc="upper left", frameon=False, ncol=3, fontsize=8)
    ax.set_title(f"{sym}: price, VWAP and alerts (grey bands = planted events)")
    fig.tight_layout()
    fig.savefig(out / "figures" / "01_price_alerts.png")
    plt.close(fig)

    # 2. Realized vs bipower volatility vs truth
    sigma = DEFAULT_SYMBOLS[sym][1]
    x = b.iloc[300:]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(x["time"], x["realized_vol_5m"], color=BLUE, linewidth=1.3, label="Realized vol")
    ax.plot(x["time"], x["bipower_vol_5m"], color=ORANGE, linewidth=1.6, label="Bipower (jump-robust) vol")
    ax.axhline(sigma, color=INK_2, linewidth=1, linestyle="--", label=f"True vol {sigma:.0%}")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(loc="upper left", frameon=False, ncol=3, fontsize=8)
    ax.set_title(f"{sym}: realized vol spikes on jumps; bipower vol stays near the truth")
    fig.tight_layout()
    fig.savefig(out / "figures" / "02_realized_vol.png")
    plt.close(fig)

    # 3. Order-flow imbalance
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.fill_between(b["time"], 0, b["ofi_1m"], where=b["ofi_1m"] >= 0, color=AQUA, linewidth=0,
                    label="net taker buying")
    ax.fill_between(b["time"], 0, b["ofi_1m"], where=b["ofi_1m"] < 0, color=ORANGE, linewidth=0,
                    label="net taker selling")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(loc="upper left", frameon=False, ncol=2, fontsize=8)
    ax.set_title(f"{sym}: 1-minute order-flow imbalance")
    fig.tight_layout()
    fig.savefig(out / "figures" / "03_order_flow.png")
    plt.close(fig)

    by_kind = alerts.groupby("kind").size().to_dict()
    md = f"""# Offline backtest report

Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · simulated {args.minutes} min of trading · {len(DEFAULT_SYMBOLS)} symbols · seed {args.seed}

## Throughput
| Trades processed | Bars | Wall time | Throughput |
|---:|---:|---:|---:|
| {stats['trades']:,} | {stats['bars']:,} | {stats['seconds']} s | **{stats['trades_per_sec']:,} trades/s** (single core) |

For scale: BTC, ETH and SOL together print roughly 50-2,000 trades/s on Binance, so one analytics process has 20x+ headroom at peak.

## Anomaly detection vs planted events
| Metric | Value |
|---|---:|
| Planted events (price jumps + volume bursts) | {ev['events']} |
| Alerts raised | {ev['alerts']} ({', '.join(f'{k}: {v}' for k, v in by_kind.items())}) |
| **Recall** (events detected) | **{ev['recall']:.0%}** |
| Recall: price jumps | {ev['recall_price_jump']:.0%} |
| Recall: volume bursts | {ev['recall_volume_burst']:.0%} |
| **Precision** (alerts that were real events) | **{ev['precision']:.0%}** |

## Volatility estimate vs truth
| Symbol | True vol | Median realized vol | Median bipower vol | Mean realized vol | Mean bipower vol |
|---|---:|---:|---:|---:|---:|
""" + "\n".join(
        f"| {s} | {sig:.0%} | {m[m['symbol'] == s]['realized_vol_5m'].iloc[300:].median():.1%} "
        f"| {m[m['symbol'] == s]['bipower_vol_5m'].iloc[300:].median():.1%} "
        f"| {m[m['symbol'] == s]['realized_vol_5m'].iloc[300:].mean():.1%} "
        f"| {m[m['symbol'] == s]['bipower_vol_5m'].iloc[300:].mean():.1%} |"
        for s, (_, sig, _, _) in DEFAULT_SYMBOLS.items()) + """

![](figures/01_price_alerts.png)
![](figures/02_realized_vol.png)
![](figures/03_order_flow.png)
"""
    (out / "backtest.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
