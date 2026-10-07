"""Transport adapters: Redpanda/Kafka, ClickHouse, alert webhooks.

Heavy client libraries are imported lazily so the analytics core (and its tests) run
with no broker or database installed.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import datetime, timezone

from .models import Alert, Bar, Metrics, Trade

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
TOPIC = os.getenv("KAFKA_TOPIC", "trades")


# --------------------------------------------------------------------------- #
# Kafka / Redpanda
# --------------------------------------------------------------------------- #
class KafkaTradeProducer:
    def __init__(self, bootstrap: str = KAFKA_BOOTSTRAP, topic: str = TOPIC):
        from confluent_kafka import Producer
        self.topic = topic
        self.p = Producer({
            "bootstrap.servers": bootstrap,
            "enable.idempotence": True,     # no duplicates on retry
            "acks": "all",
            "linger.ms": 20,                # micro-batching: throughput vs latency
            "compression.type": "zstd",
        })
        self.sent = 0

    def send(self, t: Trade) -> None:
        # key = symbol -> all trades of a symbol land in one partition, in order
        self.p.produce(self.topic, key=t.symbol, value=t.to_json(), on_delivery=self._cb)
        self.sent += 1
        self.p.poll(0)

    @staticmethod
    def _cb(err, msg):
        if err is not None:
            log.error("delivery failed: %s", err)

    def flush(self, timeout: float = 10) -> None:
        self.p.flush(timeout)


class KafkaTradeConsumer:
    """At-least-once consumer: offsets are committed only after results are stored."""

    def __init__(self, group_id: str = "analytics", bootstrap: str = KAFKA_BOOTSTRAP,
                 topic: str = TOPIC, from_beginning: bool = False):
        from confluent_kafka import Consumer
        self.c = Consumer({
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest" if from_beginning else "latest",
            "enable.auto.commit": False,
        })
        self.c.subscribe([topic])

    def poll(self, timeout: float = 1.0) -> Iterator[Trade]:
        msgs = self.c.consume(num_messages=5000, timeout=timeout)
        for m in msgs:
            if m.error():
                log.warning("consumer error: %s", m.error())
                continue
            yield Trade.from_json(m.value())

    def commit(self) -> None:
        try:
            self.c.commit(asynchronous=False)
        except Exception as e:  # nothing to commit yet
            log.debug("commit skipped: %s", e)

    def close(self) -> None:
        self.c.close()


# --------------------------------------------------------------------------- #
# ClickHouse
# --------------------------------------------------------------------------- #
def _dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class ClickHouseSink:
    def __init__(self, host: str | None = None, port: int | None = None, database: str = "crypto"):
        import clickhouse_connect
        self.client = clickhouse_connect.get_client(
            host=host or os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=port or int(os.getenv("CLICKHOUSE_PORT", "8123")),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=database,
        )

    def write_bars(self, bars: list[Bar]) -> None:
        self.client.insert("bars_1s", [
            [b.symbol, _dt(b.ts), b.open, b.high, b.low, b.close, b.volume, b.notional,
             b.buy_volume, b.trades] for b in bars],
            column_names=["symbol", "ts", "open", "high", "low", "close", "volume", "notional",
                          "buy_volume", "trades"])

    def write_metrics(self, rows: list[Metrics]) -> None:
        self.client.insert("metrics", [
            [m.symbol, _dt(m.ts), m.close, m.vwap_5m, m.vwap_dev_bps, m.realized_vol_5m,
             m.bipower_vol_5m, m.ofi_1m, m.trades_per_sec_1m, m.ret_1s_bps] for m in rows],
            column_names=["symbol", "ts", "close", "vwap_5m", "vwap_dev_bps", "realized_vol_5m",
                          "bipower_vol_5m", "ofi_1m", "trades_per_sec_1m", "ret_1s_bps"])

    def write_alerts(self, alerts: list[Alert]) -> None:
        self.client.insert("alerts", [
            [a.symbol, _dt(a.ts), a.kind, a.severity, a.score, a.detail] for a in alerts],
            column_names=["symbol", "ts", "kind", "severity", "score", "detail"])


# --------------------------------------------------------------------------- #
# Alert webhook (Slack / Discord compatible)
# --------------------------------------------------------------------------- #
class WebhookAlertSink:
    def __init__(self, url: str | None = None, min_severity: str = "warning"):
        self.url = url or os.getenv("ALERT_WEBHOOK_URL", "")
        self.min_rank = {"warning": 0, "critical": 1}[min_severity]

    def write_bars(self, bars):
        pass

    def write_metrics(self, rows):
        pass

    def write_alerts(self, alerts: list[Alert]) -> None:
        if not self.url:
            return
        import requests
        for a in alerts:
            if {"warning": 0, "critical": 1}[a.severity] < self.min_rank:
                continue
            text = (f"{'🔴' if a.severity == 'critical' else '🟠'} *{a.symbol}* {a.kind} at "
                    f"{_dt(a.ts):%H:%M:%S} UTC: {a.detail}")
            try:
                # Slack uses "text", Discord uses "content"; send both
                requests.post(self.url, data=json.dumps({"text": text, "content": text}),
                              headers={"Content-Type": "application/json"}, timeout=5)
            except requests.RequestException as e:
                log.warning("webhook failed: %s", e)
