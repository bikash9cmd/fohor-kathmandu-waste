PY ?= python
LAKE ?= lake

.PHONY: setup run releases rebuild blockade charts cost test lint validate-infra app

setup:            ## virtualenv with dev dependencies
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

run:              ## latest Overture release + HRSL -> bronze -> silver -> gold (~2 minutes, ~225 MB read)
	$(PY) -m fohor --lake $(LAKE) run

releases:         ## what upstream has, and what the lake has
	$(PY) -m fohor --lake $(LAKE) releases

rebuild:          ## rebuild silver and gold for RELEASE from bronze, no network
	$(PY) -m fohor --lake $(LAKE) rebuild --release $(RELEASE)

blockade:         ## the report for a 7-day landfill blockade
	$(PY) -m fohor --lake $(LAKE) blockade --days 7

charts:           ## docs/img from the local lake
	PYTHONPATH=. $(PY) scripts/make_charts.py --lake $(LAKE)

cost:             ## monthly cost model behind docs/COST.md
	$(PY) scripts/cost_model.py

test:
	$(PY) -m pytest -q

lint:
	ruff check .

validate-infra:   ## lint the SAM/CloudFormation template
	cfn-lint infra/template.yaml

app:              ## the Streamlit demo on http://localhost:8501 (pip install -r requirements-app.txt first)
	$(PY) -m streamlit run app.py
