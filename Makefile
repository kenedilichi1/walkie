.PHONY: setup test run clean

setup:
	bash scripts/setup_env.sh

test:
	python -m pytest -q

run:
	python -m main

clean:
	rm -rf output/* .pytest_cache src/*.egg-info
	find . -name __pycache__ -type d -exec rm -rf {} +
