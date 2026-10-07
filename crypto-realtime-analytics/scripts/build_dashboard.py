"""Generate the provisioned Grafana dashboard JSON (keeps it reviewable as code)."""
import json
from pathlib import Path

DS = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"


def target(sql, ref="A"):
    return {"refId": ref, "datasource": DS, "editorType": "sql", "format": 1,
            "queryType": "table", "rawSql": sql}


def ts_panel(pid, title, sql, x, y, w=12, h=8, unit="none", overrides=None, draw="line"):
    return {
        "id": pid, "type": "timeseries", "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql)],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {
            "drawStyle": draw, "lineWidth": 2, "fillOpacity": 0 if draw == "line" else 80,
            "showPoints": "never", "spanNulls": True}},
            "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
    }


def color(name, c):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}


S = "symbol = '${symbol}'"
panels = [
    {"id": 1, "type": "stat", "title": "Last price", "datasource": DS,
     "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
     "targets": [target(f"SELECT close FROM crypto.metrics WHERE {S} ORDER BY ts DESC LIMIT 1")],
     "fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 2}},
     "options": {"colorMode": "none", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}},
    {"id": 2, "type": "stat", "title": "Realized vol (5m, annualised)", "datasource": DS,
     "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
     "targets": [target(f"SELECT realized_vol_5m FROM crypto.metrics WHERE {S} ORDER BY ts DESC LIMIT 1")],
     "fieldConfig": {"defaults": {"unit": "percentunit", "decimals": 1}},
     "options": {"colorMode": "none", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}},
    {"id": 3, "type": "stat", "title": "Trades / sec (1m)", "datasource": DS,
     "gridPos": {"x": 12, "y": 0, "w": 6, "h": 4},
     "targets": [target(f"SELECT trades_per_sec_1m FROM crypto.metrics WHERE {S} ORDER BY ts DESC LIMIT 1")],
     "fieldConfig": {"defaults": {"decimals": 1}},
     "options": {"colorMode": "none", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}},
    {"id": 4, "type": "stat", "title": "Alerts (selected range)", "datasource": DS,
     "gridPos": {"x": 18, "y": 0, "w": 6, "h": 4},
     "targets": [target(f"SELECT count() FROM crypto.alerts WHERE {S} AND $__timeFilter(ts)")],
     "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [
         {"color": "text", "value": None}, {"color": ORANGE, "value": 1}]}}},
     "options": {"colorMode": "value", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}},

    ts_panel(5, "Price vs 5-minute VWAP",
             f"SELECT ts AS time, close AS price, vwap_5m AS vwap FROM crypto.metrics "
             f"WHERE {S} AND $__timeFilter(ts) ORDER BY ts", 0, 4, w=16, h=9, unit="currencyUSD",
             overrides=[color("price", BLUE), color("vwap", ORANGE)]),
    {"id": 6, "type": "table", "title": "Latest alerts", "datasource": DS,
     "gridPos": {"x": 16, "y": 4, "w": 8, "h": 9},
     "targets": [target("SELECT ts, symbol, kind, severity, round(score, 2) AS score, detail "
                        "FROM crypto.alerts WHERE $__timeFilter(ts) ORDER BY ts DESC LIMIT 100")],
     "fieldConfig": {"defaults": {}, "overrides": [{"matcher": {"id": "byName", "options": "severity"},
        "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                       {"id": "mappings", "value": [{"type": "value", "options": {
                           "critical": {"color": "red", "index": 0},
                           "warning": {"color": ORANGE, "index": 1}}}]}]}]}},

    ts_panel(7, "Taker buy vs sell volume (10s)",
             f"SELECT toStartOfInterval(ts, INTERVAL 10 SECOND) AS time, sum(buy_volume) AS buy, "
             f"-sum(volume - buy_volume) AS sell FROM crypto.bars_1s WHERE {S} AND $__timeFilter(ts) "
             f"GROUP BY time ORDER BY time", 0, 13, w=12, draw="bars",
             overrides=[color("buy", AQUA), color("sell", ORANGE)]),
    ts_panel(8, "Order-flow imbalance (1m)",
             f"SELECT ts AS time, ofi_1m AS ofi FROM crypto.metrics WHERE {S} AND $__timeFilter(ts) "
             f"ORDER BY ts", 12, 13, w=12, unit="percentunit", overrides=[color("ofi", BLUE)]),
    ts_panel(9, "Realized volatility (5m, annualised) - all symbols",
             "SELECT ts AS time, symbol, realized_vol_5m FROM crypto.metrics WHERE $__timeFilter(ts) "
             "ORDER BY ts", 0, 21, w=12, unit="percentunit"),
    ts_panel(12, "Realized vs jump-robust (bipower) volatility",
             f"SELECT ts AS time, realized_vol_5m AS realized, bipower_vol_5m AS bipower FROM crypto.metrics "
             f"WHERE {S} AND $__timeFilter(ts) ORDER BY ts", 0, 38, w=24, unit="percentunit",
             overrides=[color("realized", BLUE), color("bipower", ORANGE)]),
    ts_panel(10, "Distance from VWAP (bps)",
             f"SELECT ts AS time, vwap_dev_bps AS deviation FROM crypto.metrics WHERE {S} "
             f"AND $__timeFilter(ts) ORDER BY ts", 12, 21, w=12, overrides=[color("deviation", BLUE)]),
    {"id": 11, "type": "candlestick", "title": "1-minute candles (ClickHouse materialized view)",
     "datasource": DS, "gridPos": {"x": 0, "y": 29, "w": 24, "h": 9},
     "targets": [target(f"SELECT minute AS time, open, high, low, close, volume FROM crypto.bars_1m_v "
                        f"WHERE {S} AND $__timeFilter(minute) ORDER BY minute")],
     "options": {"mode": "candles+volume", "candleStyle": "candles", "colorStrategy": "open-close",
                 "colors": {"up": AQUA, "down": ORANGE}}},
]

# "symbol" rows from the all-symbols panel need a pivot to one series per symbol
next(p for p in panels if p["id"] == 9)["transformations"] = [{"id": "prepareTimeSeries", "options": {"format": "multi"}}]

dashboard = {
    "uid": "crypto-realtime", "title": "Crypto real-time market analytics",
    "tags": ["crypto", "streaming"], "timezone": "browser", "schemaVersion": 39,
    "refresh": "5s", "time": {"from": "now-30m", "to": "now"},
    "templating": {"list": [{
        "name": "symbol", "type": "query", "datasource": DS, "refresh": 1,
        "query": "SELECT DISTINCT symbol FROM crypto.metrics ORDER BY symbol",
        "definition": "SELECT DISTINCT symbol FROM crypto.metrics ORDER BY symbol",
        "current": {"text": "BTCUSDT", "value": "BTCUSDT"}}]},
    "panels": panels,
}
out = Path(__file__).resolve().parents[1] / "grafana" / "dashboards" / "crypto_realtime.json"
out.write_text(json.dumps(dashboard, indent=2))
print(f"wrote {out} ({len(panels)} panels)")
