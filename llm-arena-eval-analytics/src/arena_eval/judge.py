"""LLM-as-a-judge: does an LLM agree with human voters?

Protocol (standard in the MT-Bench / Arena-Hard literature):

1. Sample battles (stratified so every model appears).
2. Ask the judge LLM which response is better, **twice** - once in the original order
   and once with A/B swapped. A verdict only counts if it is consistent across both
   orders; otherwise it becomes a tie and is flagged as position-inconsistent.
3. Compare judge verdicts with human verdicts: raw agreement, Cohen's kappa
   (chance-corrected), and a confusion matrix.

Judge backends:
* ``anthropic`` - calls the Claude API (set ``ANTHROPIC_API_KEY``).
* ``mock``      - an offline simulated judge (noisy copy of the human label with a
  small first-position preference). Only for demos/tests; its numbers are NOT a
  finding and are labelled as such in the report.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, confusion_matrix

LABELS = ["A", "B", "tie"]

JUDGE_PROMPT = """You are an impartial expert evaluating two AI assistant responses to the same user prompt.

Judge on helpfulness, correctness, depth and clarity. Do NOT let response length, the order
of the responses, or the assistants' names influence you.

[User prompt]
{prompt}

[Response A]
{response_a}

[Response B]
{response_b}

Think briefly, then end your answer with exactly one line in this format:
VERDICT: A    or    VERDICT: B    or    VERDICT: tie"""


def y_to_label(y: float) -> str:
    return "A" if y == 1 else "B" if y == 0 else "tie"


def _swap(label: str) -> str:
    return {"A": "B", "B": "A"}.get(label, label)


def sample_for_judging(battles: pd.DataFrame, n: int = 300, seed: int = 0,
                       max_chars: int = 6000) -> pd.DataFrame:
    """Stratified sample: equal share per model_a, single-turn, responses not huge."""
    pool = battles[(battles["turn"] == 1)
                   & (battles["len_a"] < max_chars) & (battles["len_b"] < max_chars)]
    per_model = max(1, n // pool["model_a"].nunique())
    s = pool.sample(frac=1, random_state=seed).groupby("model_a").head(per_model)
    return s.sample(min(n, len(s)), random_state=seed).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class AnthropicJudge:
    def __init__(self, model: str = "claude-haiku-4-5", max_tokens: int = 400):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model, self.max_tokens = model, max_tokens

    def __call__(self, prompt: str, resp_a: str, resp_b: str) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=0,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                prompt=prompt, response_a=resp_a, response_b=resp_b)}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return parse_verdict(text)


class MockJudge:
    """Offline stand-in: agrees with the (hidden) human label with prob ``accuracy``."""

    def __init__(self, accuracy: float = 0.7, first_position_pref: float = 0.08, seed: int = 0):
        self.acc, self.pref = accuracy, first_position_pref
        self.rng = np.random.default_rng(seed)
        self._truth: str | None = None

    def set_truth(self, label: str):
        self._truth = label

    def __call__(self, prompt: str, resp_a: str, resp_b: str) -> str:
        if self.rng.random() < self.pref:
            return "A"
        if self.rng.random() < self.acc:
            return self._truth
        return self.rng.choice(LABELS)


def parse_verdict(text: str) -> str:
    m = re.findall(r"VERDICT:\s*(A|B|tie)\b", text, flags=re.IGNORECASE)
    if not m:
        return "tie"
    v = m[-1]
    return v.upper() if v.upper() in ("A", "B") else "tie"


# --------------------------------------------------------------------------- #
# Run + score
# --------------------------------------------------------------------------- #
def run_judge(sample: pd.DataFrame, backend: str = "mock", model: str = "claude-haiku-4-5",
              cache_path: str | Path | None = None) -> pd.DataFrame:
    """Judge every battle in both orders. Results are cached to JSONL so a crashed or
    rate-limited run resumes where it stopped (and you never pay twice)."""
    judge = AnthropicJudge(model) if backend == "anthropic" else MockJudge()
    cache: dict[str, dict] = {}
    if cache_path and Path(cache_path).exists():
        for line in Path(cache_path).read_text().splitlines():
            rec = json.loads(line)
            cache[rec["question_id"]] = rec

    out = []
    fh = open(cache_path, "a") if cache_path else None
    try:
        for row in sample.itertuples(index=False):
            if row.question_id in cache:
                out.append(cache[row.question_id])
                continue
            human = y_to_label(row.y)
            if isinstance(judge, MockJudge):
                judge.set_truth(human)
            v1 = judge(row.prompt, row.response_a, row.response_b)
            if isinstance(judge, MockJudge):
                judge.set_truth(_swap(human))
            v2 = _swap(judge(row.prompt, row.response_b, row.response_a))
            rec = {
                "question_id": row.question_id, "model_a": row.model_a, "model_b": row.model_b,
                "human": human, "judge_order1": v1, "judge_order2": v2,
                "judge": v1 if v1 == v2 else "tie", "consistent": v1 == v2, "backend": backend,
            }
            out.append(rec)
            if fh:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
    finally:
        if fh:
            fh.close()
    return pd.DataFrame(out)


def score_judge(results: pd.DataFrame) -> dict:
    h, j = results["human"], results["judge"]
    decisive = results[(h != "tie") & (j != "tie")]
    cm = confusion_matrix(h, j, labels=LABELS)
    return {
        "n": len(results),
        "backend": results["backend"].iloc[0],
        "agreement_all": float((h == j).mean()),
        "agreement_decisive": float((decisive["human"] == decisive["judge"]).mean()),
        "cohen_kappa": float(cohen_kappa_score(h, j, labels=LABELS)),
        "position_consistency": float(results["consistent"].mean()),
        "confusion_matrix": pd.DataFrame(cm, index=[f"human_{l}" for l in LABELS],
                                         columns=[f"judge_{l}" for l in LABELS]),
    }
