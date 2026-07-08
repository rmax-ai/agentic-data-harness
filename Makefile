.PHONY: install dev lint format test check verify clean sync

install:
	uv sync

dev:
	uv sync --extra dev

sync:
	uv sync --extra dev

lint:
	uv run ruff check src/adh/ tests/

format:
	uv run ruff format src/adh/ tests/
	uv run ruff check --fix src/adh/ tests/

check:
	uv run ruff check src/adh/ tests/
	uv run ruff format --check src/adh/ tests/

typecheck:
	uv run mypy src/adh/

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=src/adh --cov-report=term-missing

verify: check typecheck test
	@echo "All checks passed"

clean:
	rm -rf .venv
	rm -rf __pycache__
	rm -rf **/__pycache__
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf data/duckdb/*.db
