"""Static report: matplotlib figures + a Markdown summary with the headline numbers."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# Validated categorical palette (slots 1-3) + text / surface tokens.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#eef4fc", "#9cc2ef", BLUE, "#123f78"])
DIV = LinearSegmentedColormap.from_list("div", [ORANGE, "#f4f3ef", BLUE])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2,
    "ytick.color": INK_2, "text.color": INK, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "figure.dpi": 130,
})


def _save(fig, out_dir: Path, name: str) -> str:
    path = out_dir / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def fig_leaderboard(lb: pd.DataFrame, out: Path) -> str:
    lb = lb.iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(lb) + 1.2))
    y = np.arange(len(lb))
    ax.hlines(y, lb["ci_low"], lb["ci_high"], color=BLUE, linewidth=2)
    ax.scatter(lb["rating"], y, s=48, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3)
    for yi, (r, hi) in enumerate(zip(lb["rating"], lb["ci_high"])):
        ax.text(hi + 4, yi, f"{r:.0f}", va="center", fontsize=9, color=INK_2)
    ax.set_yticks(y, lb.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Bradley-Terry rating (Elo scale) with 95% bootstrap CI")
    ax.set_title("Model leaderboard")
    return _save(fig, out, "01_leaderboard")


def fig_win_matrix(pred: pd.DataFrame, out: Path) -> str:
    n = len(pred)
    fig, ax = plt.subplots(figsize=(0.55 * n + 2.5, 0.5 * n + 1.5))
    im = ax.imshow(pred.values, cmap=DIV, vmin=0, vmax=1)
    ax.set_xticks(range(n), pred.columns, rotation=45, ha="right")
    ax.set_yticks(range(n), pred.index)
    ax.grid(False)
    for i in range(n):
        for j in range(n):
            if i != j:
                v = pred.values[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if abs(v - 0.5) > 0.3 else INK)
    fig.colorbar(im, ax=ax, fraction=0.04, label="P(row model beats column model)")
    ax.set_title("Predicted head-to-head win probability")
    return _save(fig, out, "02_win_matrix")


def fig_length_curve(curve: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.fill_between(curve["log_ratio_mid"], curve["ci_low"], curve["ci_high"],
                    color=BLUE, alpha=0.15, linewidth=0)
    ax.plot(curve["log_ratio_mid"], curve["a_win_share"], color=BLUE, linewidth=2,
            marker="o", markersize=6, markeredgecolor=SURFACE)
    ax.axhline(0.5, color=INK_2, linewidth=1, linestyle="--")
    ax.axvline(0, color=GRID, linewidth=1)
    ax.set_xlabel("log( length of A / length of B )   ← A shorter   |   A longer →")
    ax.set_ylabel("Share of decisive votes won by A")
    ax.set_title("Length bias: longer answers win more often")
    return _save(fig, out, "03_length_bias")


def fig_style_shift(shift: pd.DataFrame, out: Path) -> str:
    s = shift.sort_values("rating")
    y = np.arange(len(s))
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(s) + 1.3))
    ax.hlines(y, s["rating"], s["rating_style_ctrl"], color=GRID, linewidth=3)
    ax.scatter(s["rating"], y, s=48, color=BLUE, label="Raw rating", zorder=3,
               edgecolor=SURFACE, linewidth=2)
    ax.scatter(s["rating_style_ctrl"], y, s=48, color=ORANGE, label="Length-controlled",
               zorder=3, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(y, s.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Rating (Elo scale)")
    ax.legend(loc="lower right", frameon=False)
    ax.set_title("Who was riding verbosity? Raw vs length-controlled ratings")
    return _save(fig, out, "04_style_control")


def fig_topic_ranks(mat: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(1.1 * mat.shape[1] + 3, 0.45 * mat.shape[0] + 1.8))
    im = ax.imshow(mat.values, cmap=SEQ.reversed(), aspect="auto")
    ax.set_xticks(range(mat.shape[1]), mat.columns, rotation=30, ha="right")
    ax.set_yticks(range(mat.shape[0]), mat.index)
    ax.grid(False)
    vmax = np.nanmax(mat.values)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{int(v)}", ha="center", va="center", fontsize=8,
                        color="white" if v <= vmax * 0.35 else INK)
    fig.colorbar(im, ax=ax, fraction=0.03, label="Rank within topic (1 = best)")
    ax.set_title("Rank by prompt topic (rows ordered by overall rating)")
    return _save(fig, out, "05_topic_ranks")


def fig_judge_confusion(cm: pd.DataFrame, out: Path, backend: str) -> str:
    fig, ax = plt.subplots(figsize=(5, 4.2))
    norm = cm.div(cm.sum(axis=1), axis=0)
    ax.imshow(norm.values, cmap=SEQ, vmin=0, vmax=1)
    labels = ["A", "B", "tie"]
    ax.set_xticks(range(3), labels)
    ax.set_yticks(range(3), labels)
    ax.set_xlabel("LLM judge verdict")
    ax.set_ylabel("Human verdict")
    ax.grid(False)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{cm.values[i, j]}\n({norm.values[i, j]:.0%})", ha="center",
                    va="center", fontsize=9,
                    color="white" if norm.values[i, j] > 0.55 else INK)
    title = "LLM judge vs human verdicts"
    ax.set_title(title + (" (MOCK judge)" if backend == "mock" else ""))
    return _save(fig, out, "06_judge_confusion")


def write_summary(out_dir: Path, metrics: dict, lb: pd.DataFrame, shift: pd.DataFrame,
                  figures: list[str]) -> Path:
    m = metrics
    top = lb.head(10)[["rating", "ci_low", "ci_high", "rank_ub"]]
    movers = shift.reindex(shift["rank_change"].abs().sort_values(ascending=False).index).head(5)
    judge_note = ("\n> ⚠️ The judge numbers below come from the **offline mock judge** and "
                  "are placeholders, not findings. Re-run with `--judge anthropic`.\n"
                  if m["judge"]["backend"] == "mock" else "")
    md = f"""# Chatbot Arena evaluation report

**Source:** {m['source']}  ·  **Battles analysed:** {m['n_battles']:,}  ·  **Models:** {m['n_models']}  ·  **Bootstrap rounds:** {m['n_boot']}

## Key findings
- **Leader:** `{lb.index[0]}` at {lb['rating'].iloc[0]:.0f} (95% CI {lb['ci_low'].iloc[0]:.0f}–{lb['ci_high'].iloc[0]:.0f}).
- **Position bias:** the first-shown response won {m['position']['a_win_share']:.1%} of decisive votes (95% CI {m['position']['ci_low']:.1%}–{m['position']['ci_high']:.1%}, p = {m['position']['p_value']:.2g}).
- **Length bias:** the longer response won {m['length']['longer_win_share']:.1%} of decisive votes (p = {m['length']['p_value']:.2g}); controlled coefficient = {m['length']['controlled_length_coef']:+.3f} logits per SD of length difference.
- **Online Elo vs Bradley-Terry:** Spearman ρ = {m['elo_bt_spearman']:.3f} (online Elo is order-dependent; BT is the stable estimator).
- **LLM judge:** agreement {m['judge']['agreement_decisive']:.1%} on decisive votes, Cohen's κ = {m['judge']['cohen_kappa']:.3f}, position-consistency {m['judge']['position_consistency']:.1%} (n = {m['judge']['n']}).
{judge_note}""" + (f"- **Topic clustering quality (simulator only):** adjusted Rand index vs true topics = {m['topic_ari']:.3f}.\n"
                  if m.get("topic_ari") is not None else "") + f"""
## Leaderboard (top 10)
{top.to_markdown()}

## Biggest rank changes after length control
{movers[['rank', 'rank_style_ctrl', 'rank_change', 'rating_delta']].to_markdown()}

## Figures
""" + "\n".join(f"![{f}](figures/{f})" for f in figures) + "\n"
    path = out_dir / "summary.md"
    path.write_text(md)
    (out_dir / "metrics.json").write_text(json.dumps(
        {k: v for k, v in m.items() if k != "judge"} |
        {"judge": {k: v for k, v in m["judge"].items() if k != "confusion_matrix"}},
        indent=2, default=float))
    return path
