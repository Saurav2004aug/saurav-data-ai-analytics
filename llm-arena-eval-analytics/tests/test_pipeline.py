"""Estimator tests against the simulator's known ground truth.

Run with:  pytest -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arena_eval import bias, data, judge, ratings, topics  # noqa: E402


@pytest.fixture(scope="module")
def battles():
    return data.make_synthetic_battles(n=15_000, seed=7)


@pytest.fixture(scope="module")
def unbiased():
    return data.make_synthetic_battles(n=15_000, position_bias=0.0, length_bias=0.0, seed=11)


def test_clean_schema(battles):
    assert list(battles.columns[:14]) == data.TIDY_COLUMNS
    assert set(battles["y"].unique()) <= {0.0, 0.5, 1.0}
    assert (battles["model_a"] != battles["model_b"]).all()


def test_bt_recovers_true_strengths(unbiased):
    bt, _ = ratings.fit_bradley_terry(unbiased)
    truth = pd.Series(data.SYNTH_MODELS)
    rho = spearmanr(bt.loc[truth.index], truth).statistic
    assert rho > 0.97
    # Scale check: gaps should match truth within ~25 Elo on average.
    err = (bt - bt.mean()) - (truth - truth.mean())
    assert err.abs().mean() < 25


def test_style_control_removes_verbosity_advantage(battles):
    """Verbose models should lose rating once length is controlled, terse ones gain.

    (Absolute error is not compared: ties scored as 0.5 compress the BT scale for
    both fits, so the meaningful check is *who moves and in which direction*.)
    """
    plain, _ = ratings.fit_bradley_terry(battles)
    styled, coefs = ratings.fit_bradley_terry(battles, ratings.length_style_features(battles))
    verbosity = np.log(pd.Series(data.SYNTH_VERBOSITY))
    delta = (styled - plain).loc[verbosity.index]
    assert coefs["length_diff"] > 0
    assert np.corrcoef(delta, verbosity)[0, 1] < -0.9


def test_position_bias_detected_only_when_present(battles, unbiased):
    assert bias.position_bias(battles)["p_value"] < 0.01
    assert bias.position_bias(unbiased)["p_value"] > 0.001


def test_length_bias_detected(battles):
    res = bias.length_bias(battles)
    assert res["longer_win_share"] > 0.55 and res["p_value"] < 1e-6


def test_bootstrap_ci_covers_point(unbiased):
    bt, _ = ratings.fit_bradley_terry(unbiased)
    boot = ratings.bootstrap_ratings(unbiased, n_boot=20, seed=1)
    lb = ratings.summarize_bootstrap(boot, bt)
    assert ((lb["ci_low"] <= lb["rating"] + 1) & (lb["rating"] - 1 <= lb["ci_high"])).all()
    assert lb["rank_ub"].min() == 1


def test_win_matrix_is_consistent():
    r = pd.Series({"a": 1100.0, "b": 1000.0, "c": 900.0})
    p = ratings.predicted_win_matrix(r)
    assert np.allclose(p.values + p.values.T, 1)
    assert p.loc["a", "b"] == pytest.approx(1 / (1 + 10 ** (-100 / 400)))


def test_topic_clustering_matches_truth(battles):
    from sklearn.metrics import adjusted_rand_score
    labels, names = topics.cluster_prompts(battles["prompt"], k=6)
    assert adjusted_rand_score(battles["true_topic"], labels) > 0.7
    assert len(names) == 6


def test_verdict_parser():
    assert judge.parse_verdict("reasoning...\nVERDICT: B") == "B"
    assert judge.parse_verdict("VERDICT: a then VERDICT: tie") == "tie"
    assert judge.parse_verdict("no verdict here") == "tie"


def test_mock_judge_scoring(battles):
    s = judge.sample_for_judging(battles, n=120)
    res = judge.run_judge(s, backend="mock")
    score = judge.score_judge(res)
    assert score["n"] == len(s)
    assert -1 <= score["cohen_kappa"] <= 1
    assert score["confusion_matrix"].values.sum() == len(s)
