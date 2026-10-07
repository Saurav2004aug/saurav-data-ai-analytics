"""Streaming trade -> 1-second bar aggregation."""
from __future__ import annotations

from .models import Bar, Trade


class BarAggregator:
    """Builds 1-second OHLCV bars per symbol from a trade stream.

    * A bar is emitted when the first trade of a *later* second arrives.
    * Seconds with no trades are emitted as flat bars (close carried forward, zero
      volume) so downstream rolling windows are on a regular clock. Gaps longer than
      ``max_gap_fill`` seconds (e.g. a disconnect) are not filled.
    * Trades that arrive late (older than the open bar) are folded into the open bar
      and counted in ``late_trades``, the usual trade-off for low-latency pipelines.
    """

    def __init__(self, max_gap_fill: int = 120):
        self.max_gap_fill = max_gap_fill
        self._open: dict[str, Bar] = {}
        self.late_trades = 0

    def add(self, t: Trade) -> list[Bar]:
        sec = t.ts_ms // 1000
        bar = self._open.get(t.symbol)
        if bar is None:
            self._open[t.symbol] = self._new_bar(t, sec)
            return []
        if sec < bar.ts:
            self.late_trades += 1
            sec = bar.ts
        if sec == bar.ts:
            bar.high = max(bar.high, t.price)
            bar.low = min(bar.low, t.price)
            bar.close = t.price
            bar.volume += t.qty
            bar.notional += t.price * t.qty
            bar.buy_volume += t.qty if not t.is_buyer_maker else 0.0
            bar.trades += 1
            return []
        # new second: close the open bar, fill the gap, open a new one
        done = [bar]
        gap = sec - bar.ts - 1
        if 0 < gap <= self.max_gap_fill:
            done += [Bar(t.symbol, bar.ts + k, bar.close, bar.close, bar.close, bar.close,
                         0.0, 0.0, 0.0, 0) for k in range(1, gap + 1)]
        self._open[t.symbol] = self._new_bar(t, sec)
        return done

    def flush(self) -> list[Bar]:
        bars = list(self._open.values())
        self._open.clear()
        return bars

    @staticmethod
    def _new_bar(t: Trade, sec: int) -> Bar:
        return Bar(t.symbol, sec, t.price, t.price, t.price, t.price, t.qty, t.price * t.qty,
                   t.qty if not t.is_buyer_maker else 0.0, 1)
