# AGENTS.md — Guidelines for agentic-data-harness

This document captures conventions for all contributors and AI coding agents working on this project.

## 1. Code Organization

- `src/adh/` is the package root — all application code lives here
- `src/adh/app.py` — CLI entry point (Typer), thin — delegates to modules
- `src/adh/config.py` — YAML config loading and Pydantic models
- Each subpackage has a single responsibility: agents, db, gateway, evals, tracing, memory
- `__init__.py` files are minimal (imports only)

## 2. Error Handling

- Functions raise specific exceptions, never raw `Exception`
- DuckDB errors are caught and classified deterministically (see `gateway/sql_gateway.py:_classify_error`)
- Agent errors are returned as structured feedback, not as exceptions
- OpenAI API errors are caught by tenacity retry decorators (future)

## 3. Python Conventions

- Python 3.11+ — use `| None` not `Optional`, `list[]` not `List[]`
- Pydantic v2 syntax: `model_config`, `field_validator`, `model_validate`
- All public functions have type hints
- Use `pathlib.Path` not `os.path`
- Dataclasses for lightweight data containers, Pydantic for validation/serialization

## 4. Testing

- Tests live in `tests/` mirroring the `src/adh/` structure
- Unit tests: pure functions — fingerprint, classification, validation
- Integration tests: DuckDB runner, SQL gateway, agent loop (with mock OpenAI)
- Test naming: `test_<module>_<behavior>`
- Run with `uv run pytest tests/ -v`

## 5. Documentation

- `docs/architecture.md` — system design and component diagrams
- `docs/benchmark_design.md` — rationale for benchmark design (future)
- README — project overview, quickstart, license
- AGENTS.md — this file, coding conventions

## 6. Performance

- DuckDB is in-memory by default; large benchmarks use file-backed DB
- Schema summaries are cached per run (computed once)
- SQL results are truncated to 5 rows in agent context
- JSONL traces are append-only, flushed after each run

## 7. Dependencies

- All deps in `pyproject.toml` — `uv sync --extra dev` for dev tools
- No optional heavy deps (Postgres drivers, Docker SDK, etc.)
- sqlglot: SQL parsing/normalization (Phase 3)
- tiktoken: token counting for cost estimation (future)

## 8. Formatting and Linting

- Ruff: check + format, via `uv run ruff check --fix && uv run ruff format`
- Line length: 100
- Double quotes preferred
- Import order: stdlib → third-party → first-party

## 9. Architecture Non-Negotiables

- SQL must be read-only — validated by `validate_sql()` before execution
- Agent output must be structured JSON — `AgentAction` Pydantic model
- Benchmarks must be reproducible — fixed seed, temperature 0
- Results must not be fabricated — all metrics from real execution
- No external mutations — the agent cannot INSERT/UPDATE/DELETE

## 10. References

- `docs/architecture.md` — system architecture
- `spec/agentic-data-harness-spec.md` — full project specification
