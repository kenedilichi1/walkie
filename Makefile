PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup region wizard suggest plan route voice remind daemon run serve history test lint typecheck clean

setup:
	bash scripts/setup_env.sh

region:
	$(PYTHON) -m walkie region

wizard:
	$(PYTHON) -m walkie wizard

suggest:
	$(PYTHON) -m walkie suggest

plan:
	$(PYTHON) -m walkie plan

route:
	$(PYTHON) -m walkie route

voice:
	$(PYTHON) -m walkie voice

remind:
	$(PYTHON) -m walkie remind

daemon:
	$(PYTHON) -m walkie daemon

serve:
	$(PYTHON) -m walkie serve

run:
	$(PYTHON) -m walkie run

history:
	$(PYTHON) -m walkie history

test:
	$(PYTHON) -m pytest -q --cov=walkie --cov-fail-under=84

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src/walkie

clean:
	rm -rf output/* .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name "*.egg-info" -type d -exec rm -rf {} +
