"""Streaming anomaly detection on 1-second bars.

Two complementary detectors:

* ``RobustZDetector``: rolling median / MAD z-scores of returns and log-volume. Robust
  statistics matter here: a plain mean/std z-score is itself distorted by the very
  spikes it is trying to find.
* ``IsolationForestDetector``: a multivariate model (return, volume, trade count,
  order-flow imbalance) retrained periodically on recent history. It catches
  *combinations* that look odd even when no single feature is extreme.

Both apply a per-symbol cooldown so one event produces one alert, not a storm.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .models import Alert, Bar, Metrics

MAD_TO_SIGMA = 1.4826


class RobustZDetector:
    def __init__(self, window: int = 900, warmup: int = 180, jump_warn: float = 9.0,
                 jump_crit: float = 16.0, volume_warn: float = 7.0, cooldown_s: int = 30):
        self.window, self.warmup = window, warmup
        self.jump_warn, self.jump_crit, self.volume_warn = jump_warn, jump_crit, volume_warn
        self.cooldown_s = cooldown_s
        self._rets: dict[str, deque] = {}
        self._logv: dict[str, deque] = {}
        self._last_alert: dict[tuple[str, str], int] = {}

    @staticmethod
    def _z(x: float, hist: deque) -> float:
        arr = np.fromiter(hist, float)
        med = np.median(arr)
        mad = np.median(np.abs(arr - med)) * MAD_TO_SIGMA
        return abs(x - med) / (mad + 1e-12)

    def _cooling(self, symbol: str, kind: str, ts: int) -> bool:
        last = self._last_alert.get((symbol, kind))
        return last is not None and ts - last < self.cooldown_s

    def update(self, bar: Bar, m: Metrics) -> list[Alert]:
        rets = self._rets.setdefault(bar.symbol, deque(maxlen=self.window))
        logv = self._logv.setdefault(bar.symbol, deque(maxlen=self.window))
        r, lv = m.ret_1s_bps, math.log1p(bar.volume * bar.close)   # quote volume
        alerts = []
        if len(rets) >= self.warmup:
            zr, zv = self._z(r, rets), self._z(lv, logv)
            if zr >= self.jump_warn and not self._cooling(bar.symbol, "price_jump", bar.ts):
                sev = "critical" if zr >= self.jump_crit else "warning"
                alerts.append(Alert(bar.symbol, bar.ts, "price_jump", sev, round(zr, 1),
                                    f"1s return {r:+.1f} bps ({zr:.0f} robust sigma)"))
                self._last_alert[(bar.symbol, "price_jump")] = bar.ts
            if (zv >= self.volume_warn and lv > np.median(logv)
                    and not self._cooling(bar.symbol, "volume_burst", bar.ts)):
                alerts.append(Alert(bar.symbol, bar.ts, "volume_burst", "warning", round(zv, 1),
                                    f"quote volume {bar.volume * bar.close:,.0f} ({zv:.0f} robust sigma)"))
                self._last_alert[(bar.symbol, "volume_burst")] = bar.ts
        rets.append(r)
        logv.append(lv)
        return alerts


class IsolationForestDetector:
    def __init__(self, history: int = 3600, retrain_every: int = 600, warmup: int = 900,
                 threshold: float = -0.2, gate_z: float = 3.0, cooldown_s: int = 60, seed: int = 0):
        from sklearn.ensemble import IsolationForest  # optional dependency
        self._IF = IsolationForest
        self.history, self.retrain_every, self.warmup = history, retrain_every, warmup
        self.threshold, self.cooldown_s, self.seed = threshold, cooldown_s, seed
        self.gate_z = gate_z
        self._scale: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._feats: dict[str, deque] = {}
        self._models: dict[str, object] = {}
        self._since: dict[str, int] = {}
        self._last_alert: dict[str, int] = {}

    def update(self, bar: Bar, m: Metrics) -> list[Alert]:
        s = bar.symbol
        feats = self._feats.setdefault(s, deque(maxlen=self.history))
        x = [m.ret_1s_bps, math.log1p(bar.volume * bar.close), math.log1p(bar.trades), m.ofi_1m]
        alerts = []
        model = self._models.get(s)
        # Two-stage: scoring a forest costs ~ms, so only bars where some feature is
        # beyond gate_z standard deviations are sent to the model (typically < 3%).
        mu_sd = self._scale.get(s)
        gated = mu_sd is not None and np.max(np.abs((np.array(x) - mu_sd[0]) / mu_sd[1])) >= self.gate_z
        if model is not None and gated:
            score = float(model.decision_function([x])[0])
            last = self._last_alert.get(s)
            if score < self.threshold and (last is None or bar.ts - last >= self.cooldown_s):
                alerts.append(Alert(s, bar.ts, "isolation_forest", "warning", round(score, 3),
                                    "unusual combination of return / volume / flow"))
                self._last_alert[s] = bar.ts
        feats.append(x)
        self._since[s] = self._since.get(s, 0) + 1
        if len(feats) >= self.warmup and (model is None or self._since[s] >= self.retrain_every):
            X = np.array(feats)
            self._models[s] = self._IF(n_estimators=100, contamination="auto",
                                       random_state=self.seed).fit(X)
            self._scale[s] = (X.mean(axis=0), X.std(axis=0) + 1e-9)
            self._since[s] = 0
        return alerts


class AnomalyEngine:
    def __init__(self, use_isolation_forest: bool = True, **robust_kwargs):
        self.detectors = [RobustZDetector(**robust_kwargs)]
        if use_isolation_forest:
            try:
                self.detectors.append(IsolationForestDetector())
            except ImportError:
                pass

    def update(self, bar: Bar, m: Metrics) -> list[Alert]:
        out = []
        for d in self.detectors:
            out += d.update(bar, m)
        return out
