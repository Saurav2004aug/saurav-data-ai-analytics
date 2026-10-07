"""Stream analytics service: Redpanda -> bars / metrics / anomaly detection -> ClickHouse.

    python services/analytics.py
    python services/analytics.py --no-clickhouse       # print alerts only (no database)

Delivery semantics: at-least-once. Results are written to ClickHouse first and Kafka
offsets are committed afterwards, so a crash replays (never loses) recent trades.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptostream.io import ClickHouseSink, KafkaTradeConsumer, WebhookAlertSink  # noqa: E402
from cryptostream.pipeline import LogAlertSink, Pipeline  # noqa: E402

log = logging.getLogger("analytics")
RUNNING = True


def _stop(*_):
    global RUNNING
    RUNNING = False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-clickhouse", action="store_true")
    ap.add_argument("--from-beginning", action="store_true")
    ap.add_argument("--flush-seconds", type=float, default=2.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    sinks = [LogAlertSink(), WebhookAlertSink()]
    if not args.no_clickhouse:
        for attempt in range(30):          # wait for ClickHouse to come up in docker compose
            try:
                sinks.insert(0, ClickHouseSink())
                break
            except Exception as e:
                log.info("waiting for ClickHouse (%s)", e.__class__.__name__)
                time.sleep(2)
    pipeline = Pipeline(sinks, flush_every=10_000)     # time-based flush below
    consumer = KafkaTradeConsumer(from_beginning=args.from_beginning)
    last_flush = last_log = time.time()
    try:
        while RUNNING:
            for trade in consumer.poll(timeout=0.5):
                pipeline.process(trade)
            now = time.time()
            if now - last_flush >= args.flush_seconds:
                pipeline.flush()
                consumer.commit()          # only after the sink write succeeded
                last_flush = now
            if now - last_log >= 15:
                log.info("stats %s", pipeline.stats)
                last_log = now
    finally:
        pipeline.flush()
        consumer.commit()
        consumer.close()


if __name__ == "__main__":
    main()
