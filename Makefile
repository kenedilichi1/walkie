PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup region wizard suggest remind daemon test lint typecheck clean

setup:
	bash scripts/setup_env.sh

region:
	$(PYTHON) -m walkie region

wizard:
	$(PYTHON) -m walkie wizard

suggest:
	$(PYTHON) -m walkie suggest

remind:
	$(PYTHON) -m walkie remind

daemon:
	$(PYTHON) -m walkie daemon

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src/walkie

clean:
	rm -rf output/* .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name "*.egg-info" -type d -exec rm -rf {} +
