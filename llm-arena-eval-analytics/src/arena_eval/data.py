"""Data loading and cleaning for Chatbot Arena battles.

Two sources are supported:

* ``load_arena_hf``  - the real ``lmsys/chatbot_arena_conversations`` dataset from
  Hugging Face (~33k human-voted battles). The dataset is gated: accept its terms on
  the Hub, then run ``huggingface-cli login`` once.
* ``make_synthetic_battles`` - a simulator with *known* ground truth (model strengths,
  position bias, length bias). It is used by the test suite and for offline demos,
  because it lets us check that every estimator recovers the truth.

Both return the same tidy schema (one row per battle):

    question_id, tstamp, model_a, model_b, winner, y, language, turn, anony,
    prompt, response_a, response_b, len_a, len_b
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WINNER_TO_Y = {"model_a": 1.0, "model_b": 0.0, "tie": 0.5, "tie (bothbad)": 0.5}

TIDY_COLUMNS = [
    "question_id", "tstamp", "model_a", "model_b", "winner", "y", "language",
    "turn", "anony", "prompt", "response_a", "response_b", "len_a", "len_b",
]


# --------------------------------------------------------------------------- #
# Real data
# --------------------------------------------------------------------------- #
def _assistant_text(conversation) -> str:
    """Join every assistant turn of a conversation into one string."""
    return "\n".join(m["content"] for m in conversation if m.get("role") == "assistant")


def _first_user_text(conversation) -> str:
    for m in conversation:
        if m.get("role") == "user":
            return m["content"]
    return ""


def load_arena_hf(cache_dir: str | Path | None = None) -> pd.DataFrame:
    """Download the Chatbot Arena conversations dataset and return tidy battles."""
    from datasets import load_dataset  # imported lazily: heavy, optional for tests

    ds = load_dataset("lmsys/chatbot_arena_conversations", split="train", cache_dir=cache_dir)
    raw = ds.to_pandas()

    df = pd.DataFrame({
        "question_id": raw["question_id"],
        "tstamp": pd.to_datetime(raw["tstamp"], unit="s"),
        "model_a": raw["model_a"],
        "model_b": raw["model_b"],
        "winner": raw["winner"],
        "language": raw["language"],
        "turn": raw["turn"],
        "anony": raw["anony"],
        "prompt": raw["conversation_a"].map(_first_user_text),
        "response_a": raw["conversation_a"].map(_assistant_text),
        "response_b": raw["conversation_b"].map(_assistant_text),
    })
    return clean_battles(df)


def clean_battles(df: pd.DataFrame, anonymous_only: bool = True) -> pd.DataFrame:
    """Standard cleaning used throughout the project.

    * keep anonymous battles only (model identity hidden from the voter - this is
      the LMSYS convention, since named battles leak brand preference)
    * drop self-battles and unknown winner labels
    * derive the numeric outcome ``y`` (1 = A wins, 0 = B wins, 0.5 = tie)
    * derive response lengths (characters)
    """
    out = df.copy()
    if anonymous_only and "anony" in out:
        out = out[out["anony"]]
    out = out[out["model_a"] != out["model_b"]]
    out = out[out["winner"].isin(WINNER_TO_Y)]
    out["y"] = out["winner"].map(WINNER_TO_Y).astype(float)
    out["len_a"] = out["response_a"].fillna("").str.len()
    out["len_b"] = out["response_b"].fillna("").str.len()
    out = out.drop_duplicates(subset=["question_id", "model_a", "model_b"])
    return out[TIDY_COLUMNS].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Synthetic data with known ground truth
# --------------------------------------------------------------------------- #
TOPIC_TEMPLATES = {
    "coding": [
        "write a python function to {x}", "fix this bug in my javascript code that {x}",
        "explain the time complexity of an algorithm that {x}", "write a sql query to {x}",
    ],
    "math": [
        "solve this equation step by step {x}", "what is the probability that {x}",
        "prove that {x}", "calculate the integral of {x}",
    ],
    "creative_writing": [
        "write a short poem about {x}", "write a story where {x}",
        "give me a catchy slogan for {x}", "write song lyrics about {x}",
    ],
    "advice": [
        "how can i improve my {x}", "what should i do if {x}",
        "give me tips for {x}", "is it a good idea to {x}",
    ],
    "knowledge": [
        "what is the history of {x}", "explain how {x} works",
        "who invented {x}", "what are the main causes of {x}",
    ],
    "business": [
        "write a marketing email for {x}", "create a business plan for {x}",
        "summarize the pros and cons of {x}", "draft a linkedin post about {x}",
    ],
}
# Topic-specific fillers so prompts carry realistic topical vocabulary.
FILLERS = {
    "coding": ["sorts a list", "reverses a string", "parses json", "reads a csv file",
               "handles null values", "joins two tables", "uses recursion"],
    "math": ["x squared plus 3x equals 10", "two dice sum to seven", "root 2 is irrational",
             "sin x times cos x", "a random card is an ace", "the series converges"],
    "creative_writing": ["the ocean at night", "a lonely robot", "autumn leaves",
                         "a dragon who fears fire", "first love", "a rainy city"],
    "advice": ["public speaking", "my resume", "sleep schedule", "a job interview",
               "my friend ignores me", "i feel burned out", "saving money"],
    "knowledge": ["the roman empire", "photosynthesis", "the internet", "black holes",
                  "the printing press", "world war one", "vaccines"],
    "business": ["a coffee shop", "a fitness app", "an electric car startup",
                 "our new saas product", "remote work policy", "a bakery franchise"],
}

# Relative strength (Elo-scale) of each simulated model, plus per-topic boosts, so
# topic-level leaderboards differ from the overall one (as they do in real data).
SYNTH_MODELS = {
    "gpt-4": 1180, "claude-v1": 1150, "claude-instant-v1": 1110, "gpt-3.5-turbo": 1100,
    "vicuna-13b": 1050, "palm-2": 1010, "koala-13b": 980, "mpt-7b-chat": 950,
    "oasst-pythia-12b": 930, "alpaca-13b": 900, "chatglm-6b": 880, "dolly-v2-12b": 830,
}
TOPIC_BOOST = {
    ("gpt-4", "coding"): 60, ("gpt-4", "math"): 60, ("claude-v1", "creative_writing"): 70,
    ("claude-instant-v1", "creative_writing"): 40, ("palm-2", "knowledge"): 60,
    ("vicuna-13b", "advice"): 40, ("chatglm-6b", "coding"): -60,
}
# Typical response length (characters) per model - verbose models get a length edge.
SYNTH_VERBOSITY = {
    "gpt-4": 1400, "claude-v1": 1300, "claude-instant-v1": 1100, "gpt-3.5-turbo": 1200,
    "vicuna-13b": 1250, "palm-2": 700, "koala-13b": 800, "mpt-7b-chat": 650,
    "oasst-pythia-12b": 700, "alpaca-13b": 350, "chatglm-6b": 600, "dolly-v2-12b": 400,
}


def make_synthetic_battles(
    n: int = 20_000,
    position_bias: float = 0.08,   # logit shift in favour of whichever model is shown first (A)
    length_bias: float = 0.35,     # logit shift per unit of log length ratio (A vs B)
    tie_rate: float = 0.30,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulate Arena battles from a Bradley-Terry model with built-in biases."""
    rng = np.random.default_rng(seed)
    models = np.array(list(SYNTH_MODELS))
    strength = np.array([SYNTH_MODELS[m] for m in models], dtype=float)
    topics = np.array(list(TOPIC_TEMPLATES))

    ia = rng.integers(0, len(models), n)
    ib = (ia + rng.integers(1, len(models), n)) % len(models)  # never a self-battle
    topic = topics[rng.integers(0, len(topics), n)]

    boost = np.array([
        TOPIC_BOOST.get((models[a], t), 0) - TOPIC_BOOST.get((models[b], t), 0)
        for a, b, t in zip(ia, ib, topic)
    ])
    verb = np.array([SYNTH_VERBOSITY[m] for m in models])
    len_a = np.maximum(20, rng.lognormal(np.log(verb[ia]), 0.45)).round().astype(int)
    len_b = np.maximum(20, rng.lognormal(np.log(verb[ib]), 0.45)).round().astype(int)

    logit = (np.log(10) / 400) * (strength[ia] - strength[ib] + boost)
    logit += position_bias + length_bias * np.log(len_a / len_b)
    p_a = 1 / (1 + np.exp(-logit))

    # Ties are more likely when the two responses are close in quality.
    p_tie = tie_rate * (1 - np.abs(2 * p_a - 1)) * 1.4
    u = rng.random(n)
    winner = np.where(u < p_tie, "tie",
                      np.where(rng.random(n) < p_a, "model_a", "model_b"))
    winner = np.where((winner == "tie") & (rng.random(n) < 0.35), "tie (bothbad)", winner)

    prompts = [
        rng.choice(TOPIC_TEMPLATES[t]).format(x=rng.choice(FILLERS[t])) for t in topic
    ]
    languages = rng.choice(["English", "English", "English", "English", "Chinese", "Spanish"], n)
    df = pd.DataFrame({
        "question_id": [f"synth_{i:06d}" for i in range(n)],
        "tstamp": pd.Timestamp("2023-04-24") + pd.to_timedelta(np.sort(rng.random(n)) * 90, unit="D"),
        "model_a": models[ia], "model_b": models[ib], "winner": winner,
        "language": languages, "turn": rng.choice([1, 1, 1, 2, 3], n), "anony": True,
        "prompt": prompts,
        # Placeholder texts of the simulated length (real text comes from the HF source).
        "response_a": ["x" * k for k in len_a], "response_b": ["x" * k for k in len_b],
        "true_topic": topic,
    })
    tidy = clean_battles(df)
    tidy["true_topic"] = df.set_index("question_id").loc[tidy["question_id"], "true_topic"].values
    return tidy


# --------------------------------------------------------------------------- #
# Persistence helpers (parquet when pyarrow is installed, CSV otherwise)
# --------------------------------------------------------------------------- #
def save_table(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path.with_suffix(".parquet"), index=False)
        return path.with_suffix(".parquet")
    except ImportError:
        df.to_csv(path.with_suffix(".csv"), index=False)
        return path.with_suffix(".csv")


def load_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    pq, csv = path.with_suffix(".parquet"), path.with_suffix(".csv")
    if pq.exists():
        return pd.read_parquet(pq)
    if csv.exists():
        return pd.read_csv(csv)
    raise FileNotFoundError(f"Neither {pq} nor {csv} exists - run the pipeline first.")
