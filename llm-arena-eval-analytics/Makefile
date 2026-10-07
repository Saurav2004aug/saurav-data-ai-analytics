.PHONY: install demo run judge app test lint

install:
	pip install -r requirements-dev.txt

demo:            ## offline run on simulated data (no downloads, no API key)
	python scripts/run_pipeline.py --source synthetic

run:             ## real Chatbot Arena data (needs `huggingface-cli login`)
	python scripts/run_pipeline.py --source hf --bootstrap 200

judge:           ## real data + Claude as judge on 300 battles (needs ANTHROPIC_API_KEY)
	python scripts/run_pipeline.py --source hf --judge anthropic --judge-n 300

app:
	streamlit run app/streamlit_app.py

test:
	pytest -q

lint:
	ruff check src scripts app tests
