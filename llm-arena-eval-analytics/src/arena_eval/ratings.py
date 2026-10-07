"""Rating models: online Elo, Bradley-Terry MLE, style-controlled BT, bootstrap CIs.

Bradley-Terry (BT) is the model behind the official LMSYS leaderboard. For a battle
between A and B:

    P(A beats B) = sigmoid( ln(10)/400 * (r_A - r_B)  +  beta . z )

where ``z`` are optional *style* covariates (e.g. length difference). With ``z``
omitted this is plain BT; with ``z`` included it is a *style-controlled* rating that
asks "who wins once we account for verbosity?".

Ties are handled by giving a tie a target of 0.5, which is equivalent to counting it
as half a win for each side (the LMSYS convention).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

SCALE, BASE, INIT = 400.0, 10.0, 1000.0
_K = np.log(BASE) / SCALE


# --------------------------------------------------------------------------- #
# Online Elo (order-dependent - shown for comparison, not used for the leaderboard)
# --------------------------------------------------------------------------- #
def online_elo(battles: pd.DataFrame, k: float = 4.0) -> pd.Series:
    ratings: dict[str, float] = {}
    for a, b, y in battles.sort_values("tstamp")[["model_a", "model_b", "y"]].itertuples(index=False):
        ra, rb = ratings.get(a, INIT), ratings.get(b, INIT)
        ea = 1 / (1 + BASE ** ((rb - ra) / SCALE))
        ratings[a] = ra + k * (y - ea)
        ratings[b] = rb - k * (y - ea)
    return pd.Series(ratings, name="elo").sort_values(ascending=False)


# --------------------------------------------------------------------------- #
# Bradley-Terry maximum likelihood (vectorised, with analytic gradient)
# --------------------------------------------------------------------------- #
def _design(battles: pd.DataFrame, models: list[str]):
    idx = {m: i for i, m in enumerate(models)}
    ia = battles["model_a"].map(idx).to_numpy()
    ib = battles["model_b"].map(idx).to_numpy()
    return ia, ib


def fit_bradley_terry(
    battles: pd.DataFrame,
    style_features: pd.DataFrame | None = None,
    l2: float = 1e-6,
    models: list[str] | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Fit BT ratings (and optional style coefficients) by maximum likelihood.

    Returns ``(ratings, style_coefs)``. Ratings are on the Elo scale, anchored so
    their mean is 1000. ``style_coefs`` is empty when no style features are given.
    """
    models = models or sorted(set(battles["model_a"]) | set(battles["model_b"]))
    ia, ib = _design(battles, models)
    y = battles["y"].to_numpy(dtype=float)
    Z = np.zeros((len(battles), 0)) if style_features is None else style_features.to_numpy(float)
    m, p = len(models), Z.shape[1]

    def nll(theta):
        r, beta = theta[:m], theta[m:]
        s = _K * (r[ia] - r[ib]) + Z @ beta
        # log-sigmoid, numerically stable
        log_p = -np.logaddexp(0, -s)
        log_1mp = -np.logaddexp(0, s)
        loss = -(y * log_p + (1 - y) * log_1mp).sum() + l2 * (theta @ theta)
        resid = 1 / (1 + np.exp(-s)) - y          # d loss / d s
        g_r = np.zeros(m)
        np.add.at(g_r, ia, _K * resid)
        np.add.at(g_r, ib, -_K * resid)
        grad = np.concatenate([g_r, Z.T @ resid]) + 2 * l2 * theta
        return loss, grad

    res = minimize(nll, np.zeros(m + p), jac=True, method="L-BFGS-B")
    r = res.x[:m]
    ratings = pd.Series(r - r.mean() + INIT, index=models, name="rating")
    coefs = pd.Series(res.x[m:], index=[] if style_features is None else style_features.columns,
                      name="coef")
    return ratings.sort_values(ascending=False), coefs


def length_style_features(battles: pd.DataFrame) -> pd.DataFrame:
    """Normalised length difference, the main style covariate used by LMSYS."""
    la, lb = battles["len_a"].astype(float), battles["len_b"].astype(float)
    diff = (la - lb) / (la + lb).clip(lower=1)
    return pd.DataFrame({"length_diff": (diff - diff.mean()) / diff.std()})


# --------------------------------------------------------------------------- #
# Bootstrap confidence intervals
# --------------------------------------------------------------------------- #
def bootstrap_ratings(
    battles: pd.DataFrame, n_boot: int = 200, seed: int = 0, style: bool = False,
) -> pd.DataFrame:
    """Resample battles with replacement and refit BT ``n_boot`` times.

    Returns one row per bootstrap round, one column per model.
    """
    rng = np.random.default_rng(seed)
    models = sorted(set(battles["model_a"]) | set(battles["model_b"]))
    rows = []
    for _ in range(n_boot):
        sample = battles.iloc[rng.integers(0, len(battles), len(battles))]
        feats = length_style_features(sample) if style else None
        r, _ = fit_bradley_terry(sample, feats, models=models)
        rows.append(r)
    return pd.DataFrame(rows).reset_index(drop=True)[models]


def summarize_bootstrap(boot: pd.DataFrame, point: pd.Series) -> pd.DataFrame:
    """Leaderboard table with 95% CIs and a *rank range* (upper/lower rank)."""
    table = pd.DataFrame({
        "rating": point,
        "ci_low": boot.quantile(0.025),
        "ci_high": boot.quantile(0.975),
    }).loc[point.index]
    table["ci_width"] = table["ci_high"] - table["ci_low"]
    # A model's rank is 1 + number of models whose CI lower bound is above its upper bound
    # (the statistically defensible rank used by the Arena leaderboard).
    table["rank_ub"] = [1 + (table["ci_low"] > hi).sum() for hi in table["ci_high"]]
    table.insert(0, "rank", range(1, len(table) + 1))
    return table.round(1)


# --------------------------------------------------------------------------- #
# Derived views
# --------------------------------------------------------------------------- #
def predicted_win_matrix(ratings: pd.Series) -> pd.DataFrame:
    r = ratings.to_numpy()
    p = 1 / (1 + BASE ** ((r[None, :] - r[:, None]) / SCALE))
    return pd.DataFrame(p, index=ratings.index, columns=ratings.index)


def observed_win_matrix(battles: pd.DataFrame) -> pd.DataFrame:
    """Row model's observed score vs column model (ties = 0.5), both seat orders pooled."""
    a = battles[["model_a", "model_b", "y"]].rename(columns={"model_a": "row", "model_b": "col"})
    b = battles[["model_b", "model_a", "y"]].rename(columns={"model_b": "row", "model_a": "col"})
    b = b.assign(y=1 - b["y"])
    long = pd.concat([a, b])
    return long.pivot_table(index="row", columns="col", values="y", aggfunc="mean")


def battle_counts(battles: pd.DataFrame) -> pd.DataFrame:
    pairs = pd.concat([
        battles[["model_a", "model_b"]].set_axis(["row", "col"], axis=1),
        battles[["model_b", "model_a"]].set_axis(["row", "col"], axis=1),
    ])
    return pairs.value_counts().unstack(fill_value=0)
