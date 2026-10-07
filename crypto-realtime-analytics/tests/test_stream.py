"""Tests for the streaming analytics core against the simulator's ground truth."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptostream.bars import BarAggregator  # noqa: E402
from cryptostream.metrics import MetricsEngine  # noqa: E402
from cryptostream.models import Trade, parse_binance  # noqa: E402
from cryptostream.pipeline import MemorySink, Pipeline, evaluate_alerts  # noqa: E402
from cryptostream.simulator import DEFAULT_SYMBOLS, simulate  # noqa: E402


@pytest.fixture(scope="module")
def run():
    trades, events = simulate(duration_s=3600, seed=11)
    sink = MemorySink()
    stats = Pipeline([sink]).run(trades)
    return trades, events, sink, stats


def test_parse_binance_combined_stream():
    msg = json.dumps({"stream": "btcusdt@trade", "data": {
        "e": "trade", "E": 1, "s": "BTCUSDT", "t": 42, "p": "67000.5", "q": "0.01",
        "T": 1718000000123, "m": True, "M": True}})
    t = parse_binance(msg)
    assert t == Trade("BTCUSDT", 42, 67000.5, 0.01, 1718000000123, True)
    assert t.taker_side == -1
    assert parse_binance(json.dumps({"e": "aggTrade"})) is None
    assert Trade.from_json(t.to_json()) == t


def test_bars_match_batch_computation():
    trades, _ = simulate(duration_s=300, seed=3, n_jumps=0, n_bursts=0)
    agg = BarAggregator()
    bars = [b for t in trades for b in agg.add(t)] + agg.flush()
    btc = [t for t in trades if t.symbol == "BTCUSDT"]
    by_sec: dict[int, list[Trade]] = {}
    for t in btc:
        by_sec.setdefault(t.ts_ms // 1000, []).append(t)
    for b in (b for b in bars if b.symbol == "BTCUSDT"):
        ts = by_sec.get(b.ts, [])
        if not ts:
            assert b.volume == 0 and b.trades == 0      # gap-filled bar
            continue
        assert b.open == ts[0].price and b.close == ts[-1].price
        assert b.high == max(t.price for t in ts) and b.low == min(t.price for t in ts)
        assert b.volume == pytest.approx(sum(t.qty for t in ts))
        assert b.vwap == pytest.approx(sum(t.price * t.qty for t in ts) / sum(t.qty for t in ts))
        assert b.buy_volume == pytest.approx(sum(t.qty for t in ts if not t.is_buyer_maker))


def test_gap_fill_and_late_trades():
    agg = BarAggregator()
    mk = lambda ms, p, i: Trade("X", i, p, 1.0, ms, False)  # noqa: E731
    assert agg.add(mk(1_000, 10, 1)) == []
    out = agg.add(mk(4_500, 11, 2))                  # 2 empty seconds in between
    assert [b.ts for b in out] == [1, 2, 3] and out[1].volume == 0 and out[1].close == 10
    agg.add(mk(3_900, 12, 3))                        # late trade folds into the open bar
    assert agg.late_trades == 1


def test_realized_vol_recovers_true_sigma(run):
    _, _, sink, _ = run
    for sym, (_, sigma, _, _) in DEFAULT_SYMBOLS.items():
        rv = np.median([m.realized_vol_5m for m in sink.metrics if m.symbol == sym][600:])
        assert rv == pytest.approx(sigma, rel=0.12), sym


def test_vwap_and_ofi_bounds(run):
    _, _, sink, _ = run
    ofi = np.array([m.ofi_1m for m in sink.metrics])
    assert ofi.min() >= -1 and ofi.max() <= 1
    dev = np.array([abs(m.vwap_dev_bps) for m in sink.metrics])
    assert np.median(dev) < 50


def test_order_flow_is_informative(run):
    """Simulated takers lean with the move, so 1-minute OFI should correlate with returns."""
    _, _, sink, _ = run
    ms = [m for m in sink.metrics if m.symbol == "BTCUSDT"]
    ret_1m = [math.log(ms[i].close / ms[i - 60].close) for i in range(60, len(ms))]
    ofi = [ms[i].ofi_1m for i in range(60, len(ms))]
    assert np.corrcoef(ret_1m, ofi)[0, 1] > 0.15


def test_detector_finds_planted_events_without_false_alarms(run):
    _, events, sink, _ = run
    ev = evaluate_alerts(sink.alerts, events)
    assert ev["recall_price_jump"] == 1.0
    assert ev["recall"] >= 0.85
    assert ev["precision"] >= 0.9


def test_quiet_market_produces_no_alerts():
    trades, events = simulate(duration_s=2400, seed=5, n_jumps=0, n_bursts=0)
    sink = MemorySink()
    Pipeline([sink]).run(trades)
    assert events == [] and len(sink.alerts) <= 3


def test_throughput(run):
    *_, stats = run
    assert stats["trades_per_sec"] > 5_000     # >> Binance's peak ~1-2k trades/s for these pairs


def test_metrics_engine_multi_symbol_isolation():
    from cryptostream.models import Bar
    eng = MetricsEngine()
    a = eng.update(Bar("A", 1, 100, 100, 100, 100, 1, 100, 1, 1))
    b = eng.update(Bar("B", 1, 5, 5, 5, 5, 1, 5, 0, 1))
    a2 = eng.update(Bar("A", 2, 101, 101, 101, 101, 1, 101, 1, 1))
    assert a.ret_1s_bps == 0 and b.ret_1s_bps == 0
    assert a2.ret_1s_bps == pytest.approx(math.log(1.01) * 1e4)


def test_bipower_vol_is_robust_to_jumps(run):
    """With planted jumps, mean realized vol is inflated; bipower vol stays near the truth."""
    _, _, sink, _ = run
    for sym, (_, sigma, _, _) in DEFAULT_SYMBOLS.items():
        ms = [m for m in sink.metrics if m.symbol == sym][600:]
        rv = np.mean([m.realized_vol_5m for m in ms])
        bv = np.mean([m.bipower_vol_5m for m in ms])
        assert rv > 1.3 * sigma, sym
        assert bv == pytest.approx(sigma, rel=0.15), sym
