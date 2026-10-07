"""LLM clients. Anthropic Claude by default; a scripted client for tests and demos."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Protocol

# USD per million tokens (input, output). Used only for the cost column of the eval report;
# check current pricing and update if needed.
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-4-5": (3.0, 15.0)}


@dataclass
class LLMReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class LLM(Protocol):
    model: str

    def complete(self, system: str, messages: list[dict]) -> LLMReply: ...


class AnthropicLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        import anthropic
        self.client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY
        self.model = model or os.getenv("SQLANALYST_MODEL", "claude-haiku-4-5")
        self.max_tokens = max_tokens

    def complete(self, system: str, messages: list[dict]) -> LLMReply:
        t0 = time.perf_counter()
        msg = self.client.messages.create(model=self.model, max_tokens=self.max_tokens,
                                          temperature=0, system=system, messages=messages)
        text = "".join(b.text for b in msg.content if b.type == "text")
        return LLMReply(text, msg.usage.input_tokens, msg.usage.output_tokens, time.perf_counter() - t0)


@dataclass
class ScriptedLLM:
    """Returns pre-set replies in order; records every prompt it received (for tests)."""
    replies: list[str]
    model: str = "scripted"
    calls: list[tuple[str, list[dict]]] = field(default_factory=list)

    def complete(self, system: str, messages: list[dict]) -> LLMReply:
        self.calls.append((system, [dict(m) for m in messages]))
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return LLMReply(text, input_tokens=len(system + str(messages)) // 4, output_tokens=len(text) // 4)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * p_in + output_tokens * p_out) / 1e6
