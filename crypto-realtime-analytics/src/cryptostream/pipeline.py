"""Stream processing pipeline: trades -> bars -> metrics -> alerts -> sinks.

The pipeline is transport-agnostic: the source is any iterable of Trade objects (a
Kafka consumer, a replay file, the simulator) and sinks are plain objects with
``write_bars / write_metrics / write_alerts``. That is what makes the whole service
testable without a broker or a database.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from .anomaly import AnomalyEngine
from .bars import BarAggregator
from .metrics import MetricsEngine
from .models import Alert, Bar, Metrics, Trade

log = logging.getLogger(__name__)


class Sink(Protocol):
    def write_bars(self, bars: list[Bar]) -> None: ...
    def write_metrics(self, rows: list[Metrics]) -> None: ...
    def write_alerts(self, alerts: list[Alert]) -> None: ...


@dataclass
class MemorySink:
    bars: list[Bar] = field(default_factory=list)
    metrics: list[Metrics] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)

    def write_bars(self, bars):
        self.bars += bars

    def write_metrics(self, rows):
        self.metrics += rows

    def write_alerts(self, alerts):
        self.alerts += alerts


class LogAlertSink:
    """Prints alerts; drop-in for a Slack/Discord webhook sink."""

    def write_bars(self, bars):
        pass

    def write_metrics(self, rows):
        pass

    def write_alerts(self, alerts):
        for a in alerts:
            log.warning("ALERT %-8s %s %-16s %s", a.severity.upper(), a.symbol, a.kind, a.detail)


class Pipeline:
    def __init__(self, sinks: list[Sink], flush_every: int = 500, anomaly: AnomalyEngine | None = None):
        self.bars = BarAggregator()
        self.metrics = MetricsEngine()
        self.anomaly = anomaly or AnomalyEngine()
        self.sinks = sinks
        self.flush_every = flush_every
        self._buf_bars: list[Bar] = []
        self._buf_metrics: list[Metrics] = []
        self._buf_alerts: list[Alert] = []
        self.stats = {"trades": 0, "bars": 0, "alerts": 0}

    def process(self, trade: Trade) -> None:
        self.stats["trades"] += 1
        for bar in self.bars.add(trade):
            self._on_bar(bar)
        if len(self._buf_bars) >= self.flush_every:
            self.flush()

    def _on_bar(self, bar: Bar) -> None:
        m = self.metrics.update(bar)
        alerts = self.anomaly.update(bar, m)
        self._buf_bars.append(bar)
        self._buf_metrics.append(m)
        self._buf_alerts += alerts
        self.stats["bars"] += 1
        self.stats["alerts"] += len(alerts)
        if alerts:                       # alerts are latency-sensitive: flush right away
            for s in self.sinks:
                s.write_alerts(alerts)
            self._buf_alerts.clear()

    def flush(self) -> None:
        for s in self.sinks:
            if self._buf_bars:
                s.write_bars(self._buf_bars)
            if self._buf_metrics:
                s.write_metrics(self._buf_metrics)
            if self._buf_alerts:
                s.write_alerts(self._buf_alerts)
        self._buf_bars, self._buf_metrics, self._buf_alerts = [], [], []

    def run(self, source: Iterable[Trade], final_flush: bool = True) -> dict:
        t0 = time.perf_counter()
        for trade in source:
            self.process(trade)
        if final_flush:
            for bar in self.bars.flush():
                self._on_bar(bar)
            self.flush()
        elapsed = time.perf_counter() - t0
        self.stats["seconds"] = round(elapsed, 2)
        self.stats["trades_per_sec"] = round(self.stats["trades"] / max(elapsed, 1e-9))
        self.stats["late_trades"] = self.bars.late_trades
        return self.stats


def evaluate_alerts(alerts: list[Alert], events, tolerance_s: int = 3) -> dict:
    """Precision / recall of alerts against planted simulator events.

    An event counts as detected if any alert for that symbol fires within
    ``tolerance_s`` seconds. An alert is a true positive if it is near any event.
    """
    def near(a, e):
        return a.symbol == e.symbol and abs(a.ts - e.ts) <= tolerance_s + 5  # bursts last 5s

    detected = [e for e in events if any(near(a, e) for a in alerts)]
    true_alerts = [a for a in alerts if any(near(a, e) for e in events)]
    out = {
        "events": len(events), "alerts": len(alerts),
        "recall": len(detected) / len(events) if events else float("nan"),
        "precision": len(true_alerts) / len(alerts) if alerts else float("nan"),
    }
    for kind in {e.kind for e in events}:
        ev = [e for e in events if e.kind == kind]
        out[f"recall_{kind}"] = sum(any(near(a, e) for a in alerts) for e in ev) / len(ev)
    return out
