# Recursively expanded so a venv created while building `go` is picked up.
PYTHON = $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.DEFAULT_GOAL := go

.PHONY: go setup region wizard suggest plan route voice remind daemon run serve history card qr schedule test lint typecheck gate clean

# --- everyday ---------------------------------------------------------------

go: .venv/bin/python
	$(PYTHON) -m walkie go

# First-run bootstrap only: creates .venv, so later goals use it.
.venv/bin/python:
	bash scripts/setup_env.sh

# --- one-time setup ---------------------------------------------------------

setup:
	bash scripts/setup_env.sh

region:
	$(PYTHON) -m walkie region

wizard:
	$(PYTHON) -m walkie wizard

# --- pipeline pieces (mostly for debugging) ---------------------------------

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

card:
	$(PYTHON) -m walkie card

qr:
	$(PYTHON) -m walkie qr

# --- automation and sharing -------------------------------------------------

daemon:
	$(PYTHON) -m walkie daemon

serve:
	$(PYTHON) -m walkie serve

run:
	$(PYTHON) -m walkie run

history:
	$(PYTHON) -m walkie history

schedule:
	$(PYTHON) -m walkie schedule

# --- development ------------------------------------------------------------

test:
	$(PYTHON) -m pytest -q --cov=walkie --cov-fail-under=84

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src/walkie

gate: lint typecheck test

clean:
	rm -rf output/* .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name "*.egg-info" -type d -exec rm -rf {} +
