"""Market simulator: realistic trade streams with *known* volatility and planted anomalies.

Used for offline demos, the test suite (does realized vol recover the true sigma? does
the detector find the planted jumps, and only those?) and load testing the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .metrics import SECONDS_PER_YEAR
from .models import Trade

DEFAULT_SYMBOLS = {
    # symbol: (start price, annualised vol, trades per second, median trade size)
    "BTCUSDT": (67_000.0, 0.50, 25.0, 0.004),
    "ETHUSDT": (3_400.0, 0.65, 15.0, 0.05),
    "SOLUSDT": (150.0, 0.90, 10.0, 1.5),
}


@dataclass(frozen=True)
class Event:
    symbol: str
    ts: int          # epoch seconds
    kind: str        # price_jump | volume_burst
    size_bps: float  # jump size (0 for pure volume bursts)


def simulate(duration_s: int = 3600, start_ts: int = 1_718_000_000, symbols: dict | None = None,
             n_jumps: int = 4, n_bursts: int = 4, seed: int = 0) -> tuple[list[Trade], list[Event]]:
    rng = np.random.default_rng(seed)
    symbols = symbols or DEFAULT_SYMBOLS
    trades: list[Trade] = []
    events: list[Event] = []
    trade_id = 1

    for sym, (p0, sigma, rate, size) in symbols.items():
        # plant events well inside the run, after detector warm-up, spaced apart
        n_ev = n_jumps + n_bursts
        first = min(1200, duration_s // 3)             # after detector warm-up when possible
        pool = np.arange(first, duration_s - 60, 90)
        if n_ev > len(pool):
            raise ValueError(f"duration_s={duration_s} too short for {n_ev} events per symbol")
        slots = rng.choice(pool, n_ev, replace=False)
        jump_at = {int(s): float(rng.choice([-1, 1]) * rng.uniform(60, 180)) for s in slots[:n_jumps]}
        burst_at = {int(s) for s in slots[n_jumps:]}
        events += [Event(sym, start_ts + s, "price_jump", b) for s, b in jump_at.items()]
        events += [Event(sym, start_ts + s, "volume_burst", 0.0) for s in burst_at]

        sd_sec = sigma / np.sqrt(SECONDS_PER_YEAR)
        log_p = np.log(p0)
        burst_left = 0
        for s in range(duration_s):
            if s in burst_at or s in jump_at:
                burst_left = 5
            mult = 8.0 if burst_left > 0 else 1.0
            burst_left = max(0, burst_left - 1)
            n = max(1, rng.poisson(rate * mult))
            steps = rng.normal(0, sd_sec / np.sqrt(n), n)
            if s in jump_at:                           # the jump happens mid-second
                steps[n // 2] += jump_at[s] / 1e4
            path = log_p + np.cumsum(steps)
            log_p = path[-1]
            # takers lean with the move: order flow is informative, as in real markets
            p_buy = np.clip(0.5 + 0.35 * np.sign(steps), 0.05, 0.95)
            buyer_maker = rng.random(n) > p_buy
            qty = rng.lognormal(np.log(size * (3.0 if mult > 1 else 1.0)), 0.9, n)
            offs = np.sort(rng.integers(0, 1000, n))
            for k in range(n):
                trades.append(Trade(sym, trade_id, round(float(np.exp(path[k])), 6),
                                    round(float(qty[k]), 6), (start_ts + s) * 1000 + int(offs[k]),
                                    bool(buyer_maker[k])))
                trade_id += 1

    trades.sort(key=lambda t: (t.ts_ms, t.trade_id))
    return trades, sorted(events, key=lambda e: e.ts)
