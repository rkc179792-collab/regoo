.PHONY: install test lint fmt run

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

fmt:
	ruff check --fix . && ruff format .

run:
	triad run . --no-deps --trace
