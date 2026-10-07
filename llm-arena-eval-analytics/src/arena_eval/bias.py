"""Evaluator-bias diagnostics for pairwise human preference data.

Three questions every RLHF / preference-data team asks:

1. Position bias  - does the response shown first (A) win more often than chance?
2. Length bias    - do longer responses win regardless of which model wrote them?
3. Tie behaviour  - are ties used when models are close (healthy) or at random?
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .ratings import fit_bradley_terry, length_style_features


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def position_bias(battles: pd.DataFrame) -> dict:
    """Share of decisive battles won by the first-shown response.

    Arena assigns models to seats at random, so with no bias this share is 0.5.
    """
    decisive = battles[battles["y"] != 0.5]
    wins_a, n = int((decisive["y"] == 1).sum()), len(decisive)
    test = stats.binomtest(wins_a, n, 0.5)
    lo, hi = wilson_ci(wins_a, n)
    return {
        "n_decisive": n, "a_win_share": wins_a / n, "ci_low": lo, "ci_high": hi,
        "p_value": test.pvalue,
    }


def length_bias(battles: pd.DataFrame) -> dict:
    """Does the longer response win more often, and does it survive model controls?

    * raw: share of decisive battles won by the longer response (binomial test)
    * controlled: style coefficient from a BT model that already accounts for which
      models fought, so it isolates a pure verbosity effect.
    """
    decisive = battles[(battles["y"] != 0.5) & (battles["len_a"] != battles["len_b"])]
    longer_is_a = decisive["len_a"] > decisive["len_b"]
    longer_won = ((decisive["y"] == 1) & longer_is_a) | ((decisive["y"] == 0) & ~longer_is_a)
    k, n = int(longer_won.sum()), len(decisive)
    lo, hi = wilson_ci(k, n)

    _, coefs = fit_bradley_terry(battles, length_style_features(battles))
    return {
        "n_decisive": n, "longer_win_share": k / n, "ci_low": lo, "ci_high": hi,
        "p_value": stats.binomtest(k, n, 0.5).pvalue,
        "controlled_length_coef": float(coefs["length_diff"]),
    }


def length_win_curve(battles: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Win share of response A by decile of log length ratio (A/B)."""
    df = battles[battles["y"] != 0.5].copy()
    df["log_ratio"] = np.log((df["len_a"] + 1) / (df["len_b"] + 1))
    df["bin"] = pd.qcut(df["log_ratio"], bins, duplicates="drop")
    g = df.groupby("bin", observed=True)
    out = pd.DataFrame({
        "log_ratio_mid": g["log_ratio"].median(),
        "a_win_share": g["y"].mean(),
        "n": g.size(),
    }).reset_index(drop=True)
    ci = [wilson_ci(int(round(s * n)), n) for s, n in zip(out["a_win_share"], out["n"])]
    out["ci_low"], out["ci_high"] = zip(*ci)
    return out


def tie_rate_by_gap(battles: pd.DataFrame, ratings: pd.Series, bins: int = 6) -> pd.DataFrame:
    """Tie rate as a function of the rating gap between the two models."""
    df = battles.copy()
    df["gap"] = (df["model_a"].map(ratings) - df["model_b"].map(ratings)).abs()
    df["is_tie"] = df["y"] == 0.5
    df["gap_bin"] = pd.qcut(df["gap"], bins, duplicates="drop")
    g = df.groupby("gap_bin", observed=True)
    return pd.DataFrame({
        "gap_mid": g["gap"].median(), "tie_rate": g["is_tie"].mean(), "n": g.size(),
    }).reset_index(drop=True)


def style_rank_shift(plain: pd.Series, styled: pd.Series) -> pd.DataFrame:
    """Compare plain vs length-controlled leaderboards: who was riding verbosity?"""
    df = pd.DataFrame({"rating": plain, "rating_style_ctrl": styled})
    df["rank"] = df["rating"].rank(ascending=False).astype(int)
    df["rank_style_ctrl"] = df["rating_style_ctrl"].rank(ascending=False).astype(int)
    df["rank_change"] = df["rank"] - df["rank_style_ctrl"]
    df["rating_delta"] = df["rating_style_ctrl"] - df["rating"]
    return df.sort_values("rank").round(1)
