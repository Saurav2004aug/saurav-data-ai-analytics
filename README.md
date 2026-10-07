# Data, AI & Analytics Portfolio

A portfolio of **production-style analytics and AI systems** covering modern data warehousing, LLM evaluation, natural-language SQL, and real-time market analytics.

The projects emphasize **statistical rigor, data quality, evaluation, reliability, and production-oriented engineering** rather than notebook-only analysis.

## Projects

| Project | Focus | Highlights |
|---|---|---|
| **[Olist Analytics Warehouse](./olist-analytics-warehouse)** | Modern Data Stack / BI | DuckDB, dbt, Dagster, Evidence.dev, star schema, ~80 data tests, RFM/cohort analytics |
| **[LLM Evaluation Analytics](./llm-arena-eval-analytics)** | AI Evaluation / Statistics | Bradley-Terry MLE, bootstrap CIs, position & length bias, topic analysis, LLM-as-judge |
| **[AI SQL Analyst](./ai-sql-analyst)** | GenAI / Data Applications | Text-to-SQL, semantic retrieval, SQL guardrails, self-correction, DuckDB, Streamlit/FastAPI |
| **[Real-Time Crypto Analytics](./crypto-realtime-analytics)** | Streaming / Data Engineering | Binance WebSocket, Redpanda, ClickHouse, real-time microstructure metrics, anomaly detection, Grafana |

## 1. Olist E-commerce Analytics Warehouse

A production-style modern data stack built around the Brazilian Olist marketplace dataset.

**Pipeline:** raw CSVs → DuckDB → dbt staging/intermediate/core marts → analytics marts → Evidence.dev dashboard + automated insights

**What stands out**
- Star-schema warehouse with incremental fact modelling
- Dagster orchestration, asset checks and scheduled runs
- ~80 data-quality tests covering uniqueness, nulls, relationships and business rules
- Cohort, RFM, delivery, seller and category analytics
- Cross-database SQL macros for DuckDB/SQLite portability

**Best for:** Data Analyst, Analytics Engineer, Data Engineer roles.

## 2. LLM Evaluation Analytics

A statistical evaluation framework for noisy human preference data inspired by the public LMSYS Chatbot Arena dataset.

**What stands out**
- Bradley-Terry maximum-likelihood ratings compared with online Elo
- Bootstrap confidence intervals and statistical ranks
- Position bias, length bias and tie-behaviour analysis
- Topic-level leaderboards using TF-IDF/LSA/KMeans
- LLM-as-a-judge evaluation with two presentation orders and Cohen's κ
- Simulator-based validation with known ground truth

**Best for:** Data Science, ML/AI Analytics, AI Evaluation and Research-oriented roles.

## 3. AI SQL Analyst

A natural-language analytics application that converts business questions into SQL and returns results, charts and concise answers.

**What stands out**
- Semantic-layer retrieval with TF-IDF and join closure
- Four prompting/evaluation strategies
- SQL security guardrails and read-only database execution
- Query limits and timeouts
- Self-correction for execution errors
- 40-question execution-accuracy benchmark and automated tests
- Streamlit UI + FastAPI service

**Best for:** GenAI, Analytics Engineering, Data Applications and AI Engineering roles.

## 4. Real-Time Crypto Market Analytics

A streaming analytics platform that consumes live Binance trades and computes market-microstructure metrics in near real time.

**Pipeline:** Binance WebSocket → Redpanda → ClickHouse + Python analytics → Grafana

**What stands out**
- 1-second OHLCV, VWAP, realized volatility, bipower variation and order-flow imbalance
- Robust median/MAD anomaly detection plus gated Isolation Forest
- ClickHouse Kafka engine and materialized views
- At-least-once processing and replayable analytics core
- Docker Compose deployment with Grafana dashboard
- Offline simulator with planted ground truth for validation

**Best for:** Data Engineering, Streaming Analytics, Quant/Data Infrastructure roles.

## Technical Themes

**Analytics & Statistics**
- Hypothesis testing, confidence intervals, bootstrap
- Bradley-Terry models, Elo, Cohen's κ
- Cohort/RFM analysis, market microstructure
- Experiment-style validation with simulated ground truth

**Data Engineering**
- SQL, DuckDB, ClickHouse
- dbt, Dagster, Redpanda/Kafka APIs
- Data-quality testing and lineage
- Batch + streaming pipelines

**AI / GenAI**
- Text-to-SQL
- Semantic retrieval and few-shot prompting
- LLM evaluation and LLM-as-a-judge
- Guardrails and evaluation harnesses

**Tools**
- Python, pandas, NumPy, SciPy, scikit-learn
- Streamlit, FastAPI, Plotly, Grafana
- Docker, GitHub Actions, pytest, SQLFluff

## Repository Structure

```text
saurav-data-ai-analytics/
├── ai-sql-analyst/
├── crypto-realtime-analytics/
├── llm-arena-eval-analytics/
├── olist-analytics-warehouse/
├── README.md
└── .gitignore
```

## Important Note on Results

Some projects include **offline/synthetic simulator results so the repositories can run reproducibly without external credentials or datasets**. Where a README labels numbers as synthetic, simulated, placeholder, or requiring a real-data run, those figures should not be interpreted as production findings.

For methodology and reproducibility details, see each project's README.

## Portfolio Positioning

If you're reviewing this repository for a role:

- **Data Analyst / Analytics:** start with **Olist Analytics Warehouse**
- **AI / Data Science:** start with **LLM Evaluation Analytics**
- **GenAI / AI Engineering:** start with **AI SQL Analyst**
- **Data Engineering / Streaming:** start with **Real-Time Crypto Analytics**

---

Built with Python, SQL and modern data/AI tooling.
