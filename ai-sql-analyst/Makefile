.PHONY: install db app api eval eval-offline test lint

install:
	pip install -r requirements-dev.txt

db:              ## build the demo warehouse (data/olist.duckdb)
	PYTHONPATH=src python -m sqlanalyst.demo_db

db-real:         ## build it from the real Olist CSVs:  make db-real RAW=path/to/csvs
	PYTHONPATH=src python -m sqlanalyst.demo_db --raw-dir $(RAW)

app:             ## chat UI at http://localhost:8501  (needs ANTHROPIC_API_KEY)
	streamlit run app/streamlit_app.py

api:             ## REST API at http://localhost:8000/docs
	uvicorn app.api:app --reload

eval:            ## benchmark all 4 strategies with Claude (~160 short API calls)
	PYTHONPATH=src python -m sqlanalyst.evaluate
	python scripts/plot_eval.py reports/eval_claude_summary.csv

eval-offline:    ## harness self-checks, no API key: oracle must score 100%
	PYTHONPATH=src python -m sqlanalyst.evaluate --llm oracle --strategies full
	PYTHONPATH=src python -m sqlanalyst.evaluate --llm noisy-oracle --strategies retrieval_fewshot full

test:
	pytest -q

lint:
	ruff check src app scripts tests
