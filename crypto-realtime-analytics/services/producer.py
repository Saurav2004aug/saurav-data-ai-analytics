"""Market data producer: Binance WebSocket (or replay / simulator) -> Redpanda topic.

    python services/producer.py --source live --symbols btcusdt ethusdt solusdt
    python services/producer.py --source simulate --speed 5       # offline, 5x real time
    python services/producer.py --source replay --file data/trades.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptostream.io import KafkaTradeProducer  # noqa: E402
from cryptostream.models import Trade, parse_binance  # noqa: E402
from cryptostream.simulator import simulate  # noqa: E402

# market-data-only endpoint (no account needed); stream.binance.com:9443 also works
WS_BASE = "wss://data-stream.binance.vision/stream?streams="
log = logging.getLogger("producer")
STOP = asyncio.Event()


async def live(producer: KafkaTradeProducer, symbols: list[str], record: Path | None) -> None:
    import websockets

    url = WS_BASE + "/".join(f"{s.lower()}@trade" for s in symbols)
    backoff = 1
    rec = open(record, "a") if record else None
    while not STOP.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_queue=10_000) as ws:
                log.info("connected: %s", url)
                backoff = 1
                last_log = time.time()
                async for raw in ws:
                    trade = parse_binance(raw)
                    if trade is None:
                        continue
                    producer.send(trade)
                    if rec:
                        rec.write(trade.to_json() + "\n")
                    if time.time() - last_log > 10:
                        log.info("sent %s trades (latency %.0f ms)", f"{producer.sent:,}",
                                 time.time() * 1000 - trade.ts_ms)
                        last_log = time.time()
                    if STOP.is_set():
                        break
        except (OSError, websockets.ConnectionClosed) as e:
            # Binance drops connections every 24h and on network blips: reconnect with backoff
            log.warning("websocket closed (%s); reconnecting in %ss", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
    if rec:
        rec.close()


def paced(trades: list[Trade], producer: KafkaTradeProducer, speed: float) -> None:
    """Send historical/simulated trades, preserving inter-arrival times (scaled by speed)."""
    if not trades:
        return
    t0_data, t0_wall = trades[0].ts_ms, time.time()
    shift = int(t0_wall * 1000) - t0_data            # re-stamp to "now" so dashboards look live
    for t in trades:
        due = t0_wall + (t.ts_ms - t0_data) / 1000 / speed
        delay = due - time.time()
        if delay > 0:
            time.sleep(delay)
        producer.send(Trade(t.symbol, t.trade_id, t.price, t.qty,
                            t0_data + int((t.ts_ms - t0_data) / speed) + shift, t.is_buyer_maker))
    producer.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["live", "simulate", "replay"], default="live")
    ap.add_argument("--symbols", nargs="+", default=["btcusdt", "ethusdt", "solusdt"])
    ap.add_argument("--file", help="JSONL of trades for --source replay")
    ap.add_argument("--record", help="also append live trades to this JSONL file")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--duration", type=int, default=3600, help="simulated seconds")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    producer = KafkaTradeProducer()
    try:
        if args.source == "live":
            loop = asyncio.new_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, STOP.set)
                except NotImplementedError:   # Windows
                    pass
            loop.run_until_complete(live(producer, args.symbols, Path(args.record) if args.record else None))
        elif args.source == "simulate":
            trades, events = simulate(duration_s=args.duration)
            log.info("simulating %s trades; planted events: %s", f"{len(trades):,}",
                     json.dumps([asdict(e) for e in events[:5]]) + " ...")
            paced(trades, producer, args.speed)
        else:
            trades = [Trade.from_json(line) for line in open(args.file)]
            paced(trades, producer, args.speed)
    finally:
        producer.flush()
        log.info("done, %s trades sent", f"{producer.sent:,}")


if __name__ == "__main__":
    main()
