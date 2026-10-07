.PHONY: install synthetic download ingest build test harness report dagster dashboard docs lint all

install:
	pip install -r requirements-dev.txt

synthetic:           ## Olist-shaped demo data (no Kaggle account needed)
	python ingestion/generate_synthetic.py --out data/raw

download:            ## real Olist data from Kaggle (needs ~/.kaggle/kaggle.json)
	python ingestion/ingest.py --download

ingest:              ## load data/raw/*.csv into DuckDB (schema raw)
	python ingestion/ingest.py

build:               ## seeds + models + tests
	cd dbt && dbt build --profiles-dir .

docs:                ## dbt docs site with full lineage graph
	cd dbt && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .

report:              ## charts + insights.md from the marts
	python analysis/insights_report.py

harness:             ## build + test every model on SQLite (no dbt / DuckDB needed)
	python tests/dbt_sqlite_harness.py

test:
	pytest -q

lint:
	sqlfluff lint dbt/models

dagster:             ## orchestration UI at http://localhost:3000
	dagster dev -f orchestration/definitions.py

dashboard:           ## Evidence.dev BI-as-code dashboard at http://localhost:3000
	test -d evidence-app || npx --yes degit evidence-dev/template evidence-app
	rm -rf evidence-app/pages/* && cp -r evidence/pages/* evidence-app/pages/
	mkdir -p evidence-app/sources/olist && cp evidence/sources/olist/* evidence-app/sources/olist/
	cp warehouse/olist.duckdb evidence-app/sources/olist/olist.duckdb
	cd evidence-app && npm install && npm run sources && npm run dev

all: synthetic ingest build report
