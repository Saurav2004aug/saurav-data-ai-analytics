"""Core data types and Binance message parsing."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    trade_id: int
    price: float
    qty: float
    ts_ms: int                 # exchange trade time, epoch milliseconds
    is_buyer_maker: bool       # True => the aggressor was a SELLER (taker sell)

    @property
    def taker_side(self) -> int:
        """+1 for an aggressive buy, -1 for an aggressive sell."""
        return -1 if self.is_buyer_maker else 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "Trade":
        d = json.loads(raw)
        return cls(d["symbol"], int(d["trade_id"]), float(d["price"]), float(d["qty"]),
                   int(d["ts_ms"]), bool(d["is_buyer_maker"]))


def parse_binance(message: str | bytes | dict) -> Trade | None:
    """Parse a Binance `<symbol>@trade` event (raw or combined-stream envelope).

    Example payload::

        {"e":"trade","E":1718000000123,"s":"BTCUSDT","t":3456789,"p":"67012.10",
         "q":"0.0015","T":1718000000120,"m":true,"M":true}
    """
    d = json.loads(message) if isinstance(message, (str, bytes)) else message
    if "data" in d and "stream" in d:          # combined stream envelope
        d = d["data"]
    if d.get("e") != "trade":
        return None
    return Trade(symbol=d["s"], trade_id=int(d["t"]), price=float(d["p"]), qty=float(d["q"]),
                 ts_ms=int(d["T"]), is_buyer_maker=bool(d["m"]))


@dataclass(slots=True)
class Bar:
    """One-second OHLCV bar with order-flow fields."""
    symbol: str
    ts: int                    # bar start, epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float              # base asset
    notional: float            # quote asset (sum price*qty) -> VWAP = notional / volume
    buy_volume: float          # taker-buy base volume
    trades: int

    @property
    def vwap(self) -> float:
        return self.notional / self.volume if self.volume else self.close

    @property
    def sell_volume(self) -> float:
        return self.volume - self.buy_volume


@dataclass(slots=True)
class Metrics:
    symbol: str
    ts: int
    close: float
    vwap_5m: float
    vwap_dev_bps: float        # (close - vwap) / vwap in basis points
    realized_vol_5m: float     # annualised, from 1-second log returns
    bipower_vol_5m: float      # jump-robust volatility (Barndorff-Nielsen & Shephard)
    ofi_1m: float              # order-flow imbalance in [-1, 1] over the last minute
    trades_per_sec_1m: float
    ret_1s_bps: float


@dataclass(slots=True)
class Alert:
    symbol: str
    ts: int
    kind: str                  # price_jump | volume_burst | isolation_forest
    severity: str              # warning | critical
    score: float
    detail: str
