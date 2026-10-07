PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup region wizard test run clean

setup:
	bash scripts/setup_env.sh

region:
	$(PYTHON) scripts/fetch_region.py

wizard:
	$(PYTHON) -m walkie.ui.wizard

test:
	$(PYTHON) -m pytest -q

run:
	$(PYTHON) -m main

clean:
	rm -rf output/* .pytest_cache src/*.egg-info
	find . -name __pycache__ -type d -exec rm -rf {} +
