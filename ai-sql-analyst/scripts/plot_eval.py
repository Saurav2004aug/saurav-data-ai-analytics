"""Chart the benchmark results:  python scripts/plot_eval.py reports/eval_claude_summary.csv"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK_2, GRID, SURFACE = "#52514e", "#e6e5e0", "#fcfcfb"
plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
                     "axes.grid": True, "grid.color": GRID, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "xtick.color": INK_2, "ytick.color": INK_2, "figure.dpi": 130})

path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/eval_claude_summary.csv")
s = pd.read_csv(path, index_col=0)
diffs = [c for c in ["EX_easy", "EX_medium", "EX_hard"] if c in s.columns]
x = np.arange(len(s))
w = 0.8 / len(diffs)
fig, ax = plt.subplots(figsize=(8, 4))
for i, (col, color) in enumerate(zip(diffs, [BLUE, ORANGE, AQUA])):
    bars = ax.bar(x + i * w - 0.4 + w / 2, s[col], w * 0.92, color=color, label=col[3:])
    ax.bar_label(bars, labels=[f"{v:.0%}" for v in s[col]], fontsize=8, color=INK_2, padding=2)
ax.set_xticks(x, s.index)
ax.set_ylim(0, 1.12)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, ncol=3, loc="upper left")
ax.set_title("Execution accuracy by strategy and difficulty")
out = path.parent / "figures" / "eval_accuracy.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.tight_layout()
fig.savefig(out)
print(f"saved {out}")
