"""O(1) rolling market metrics computed per symbol from 1-second bars."""
from __future__ import annotations

import math
from collections import deque

from .models import Bar, Metrics

SECONDS_PER_YEAR = 365 * 24 * 3600  # crypto trades 24/7


class _RollingSum:
    """Fixed-length window keeping running sums of several fields."""

    def __init__(self, size: int, n_fields: int):
        self.size = size
        self.buf: deque[tuple[float, ...]] = deque()
        self.sums = [0.0] * n_fields
        self._since_resync = 0

    def push(self, values: tuple[float, ...]) -> None:
        self.buf.append(values)
        for i, v in enumerate(values):
            self.sums[i] += v
        if len(self.buf) > self.size:
            old = self.buf.popleft()
            for i, v in enumerate(old):
                self.sums[i] -= v
        self._since_resync += 1
        if self._since_resync >= 10_000:       # guard against float drift on long runs
            self.sums = [math.fsum(col) for col in zip(*self.buf)]
            self._since_resync = 0

    def __len__(self) -> int:
        return len(self.buf)

    @property
    def full(self) -> bool:
        return len(self.buf) == self.size


class SymbolMetrics:
    def __init__(self, symbol: str, vwap_window: int = 300, vol_window: int = 300,
                 flow_window: int = 60):
        self.symbol = symbol
        self.vwap = _RollingSum(vwap_window, 2)          # volume, notional
        self.rets = _RollingSum(vol_window, 2)           # r, r^2
        self.flow = _RollingSum(flow_window, 3)          # buy volume, volume, trades
        self.bipower = _RollingSum(vol_window, 1)        # |r_t| * |r_t-1|
        self.prev_close: float | None = None
        self.prev_abs_r = 0.0

    def update(self, bar: Bar) -> Metrics:
        r = math.log(bar.close / self.prev_close) if self.prev_close else 0.0
        self.prev_close = bar.close
        self.vwap.push((bar.volume, bar.notional))
        self.rets.push((r, r * r))
        self.flow.push((bar.buy_volume, bar.volume, float(bar.trades)))
        self.bipower.push((abs(r) * self.prev_abs_r,))
        self.prev_abs_r = abs(r)

        vol_sum, notional_sum = self.vwap.sums
        vwap = notional_sum / vol_sum if vol_sum > 0 else bar.close
        n = len(self.rets)
        s, ss = self.rets.sums
        var = max(0.0, (ss - s * s / n) / (n - 1)) if n > 1 else 0.0
        # Bipower variation: a single jump enters only as |jump| * |normal return|, so this
        # estimate stays close to the diffusive vol while realized vol spikes. RV - BV
        # therefore isolates the jump component.
        bv_var = (math.pi / 2) * self.bipower.sums[0] / max(1, len(self.bipower) - 1)
        buy, total, trades = self.flow.sums
        return Metrics(
            symbol=self.symbol, ts=bar.ts, close=bar.close, vwap_5m=vwap,
            vwap_dev_bps=(bar.close - vwap) / vwap * 1e4,
            realized_vol_5m=math.sqrt(var * SECONDS_PER_YEAR),
            bipower_vol_5m=math.sqrt(max(0.0, bv_var) * SECONDS_PER_YEAR),
            ofi_1m=(2 * buy - total) / total if total > 0 else 0.0,
            trades_per_sec_1m=trades / len(self.flow),
            ret_1s_bps=r * 1e4,
        )


class MetricsEngine:
    """Keeps one SymbolMetrics per symbol."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._by_symbol: dict[str, SymbolMetrics] = {}

    def update(self, bar: Bar) -> Metrics:
        sm = self._by_symbol.get(bar.symbol)
        if sm is None:
            sm = self._by_symbol[bar.symbol] = SymbolMetrics(bar.symbol, **self.kwargs)
        return sm.update(bar)
