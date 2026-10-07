-- ClickHouse schema. Runs automatically on first container start.
CREATE DATABASE IF NOT EXISTS crypto;

-- 1) Kafka engine: ClickHouse consumes the Redpanda topic directly (no extra service).
CREATE TABLE IF NOT EXISTS crypto.trades_queue
(
    symbol         String,
    trade_id       UInt64,
    price          Float64,
    qty            Float64,
    ts_ms          UInt64,
    is_buyer_maker Bool
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'trades',
         kafka_group_name = 'clickhouse_trades',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1;

-- 2) Raw trade store, partitioned by day, 30-day retention.
CREATE TABLE IF NOT EXISTS crypto.trades
(
    symbol         LowCardinality(String),
    trade_id       UInt64,
    price          Float64,
    qty            Float64,
    ts             DateTime64(3, 'UTC'),
    is_buyer_maker Bool
)
ENGINE = MergeTree
PARTITION BY toDate(ts)
ORDER BY (symbol, ts, trade_id)
TTL toDateTime(ts) + INTERVAL 30 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS crypto.trades_mv TO crypto.trades AS
SELECT symbol, trade_id, price, qty,
       fromUnixTimestamp64Milli(toInt64(ts_ms), 'UTC') AS ts,
       is_buyer_maker
FROM crypto.trades_queue;

-- 3) 1-minute OHLCV rolled up incrementally at insert time (AggregatingMergeTree).
CREATE TABLE IF NOT EXISTS crypto.bars_1m
(
    symbol     LowCardinality(String),
    minute     DateTime('UTC'),
    open       AggregateFunction(argMin, Float64, DateTime64(3, 'UTC')),
    high       SimpleAggregateFunction(max, Float64),
    low        SimpleAggregateFunction(min, Float64),
    close      AggregateFunction(argMax, Float64, DateTime64(3, 'UTC')),
    volume     SimpleAggregateFunction(sum, Float64),
    notional   SimpleAggregateFunction(sum, Float64),
    buy_volume SimpleAggregateFunction(sum, Float64),
    trades     SimpleAggregateFunction(sum, UInt64)
)
ENGINE = AggregatingMergeTree
ORDER BY (symbol, minute);

CREATE MATERIALIZED VIEW IF NOT EXISTS crypto.bars_1m_mv TO crypto.bars_1m AS
SELECT symbol,
       toStartOfMinute(ts)             AS minute,
       argMinState(price, ts)          AS open,
       max(price)                      AS high,
       min(price)                      AS low,
       argMaxState(price, ts)          AS close,
       sum(qty)                        AS volume,
       sum(price * qty)                AS notional,
       sumIf(qty, NOT is_buyer_maker)  AS buy_volume,
       count()                         AS trades
FROM crypto.trades
GROUP BY symbol, minute;

CREATE VIEW IF NOT EXISTS crypto.bars_1m_v AS
SELECT symbol, minute,
       argMinMerge(open)                  AS open,
       max(high)                          AS high,
       min(low)                           AS low,
       argMaxMerge(close)                 AS close,
       sum(volume)                        AS volume,
       sum(notional) / sum(volume)        AS vwap,
       sum(buy_volume)                    AS buy_volume,
       sum(volume) - sum(buy_volume)      AS sell_volume,
       sum(trades)                        AS trades
FROM crypto.bars_1m
GROUP BY symbol, minute;

-- 4) Tables written by the Python analytics service.
CREATE TABLE IF NOT EXISTS crypto.bars_1s
(
    symbol LowCardinality(String), ts DateTime('UTC'),
    open Float64, high Float64, low Float64, close Float64,
    volume Float64, notional Float64, buy_volume Float64, trades UInt32
)
ENGINE = MergeTree ORDER BY (symbol, ts) TTL ts + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS crypto.metrics
(
    symbol LowCardinality(String), ts DateTime('UTC'),
    close Float64, vwap_5m Float64, vwap_dev_bps Float64, realized_vol_5m Float64, bipower_vol_5m Float64,
    ofi_1m Float64, trades_per_sec_1m Float64, ret_1s_bps Float64
)
ENGINE = MergeTree ORDER BY (symbol, ts) TTL ts + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS crypto.alerts
(
    symbol LowCardinality(String), ts DateTime('UTC'),
    kind LowCardinality(String), severity LowCardinality(String),
    score Float64, detail String
)
ENGINE = MergeTree ORDER BY (ts, symbol) TTL ts + INTERVAL 90 DAY;
