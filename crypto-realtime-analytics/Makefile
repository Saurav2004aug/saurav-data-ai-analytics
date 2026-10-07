.PHONY: up up-sim down logs test report bench lint

up:              ## full stack with LIVE Binance data
	docker compose up -d --build

up-sim:          ## full stack with simulated data (offline, planted anomalies)
	PRODUCER_SOURCE=simulate docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f analytics producer

test:
	pytest -q

report:          ## offline backtest: charts + detection precision/recall
	python scripts/offline_report.py

lint:
	ruff check src services scripts tests
