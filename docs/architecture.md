# agentic-data-harness Architecture

## Problem statement

Measure whether agent-native infrastructure (query caching and corrective memory) reduces speculative waste in data-agent workloads.

## Design goals

1. Reproducible benchmarks with fixed seeds
2. Deterministic SQL safety and classification
3. Structured traces for auditability
4. Minimal dependencies — DuckDB, no Postgres, no Docker

## Component diagram

```
┌────────────────────┐
│ Benchmark Task Set │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ Agent Runner       │
│ raw/cache/memory   │
└─────────┬──────────┘
          │ model call
          v
┌────────────────────┐
│ SQL Proposal       │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ SQL Gateway        │
│ - validate         │
│ - fingerprint      │
│ - cache lookup     │
│ - execute          │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ DuckDB             │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ Trace Logger       │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ Failure Classifier │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ Corrective Memory  │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ Eval Report        │
└────────────────────┘
```

## Module layout

```
src/adh/
  app.py              CLI entry point (Typer)
  config.py           YAML config + env loading
  agents/
    openai_sql_agent.py  OpenAI agent loop
    prompts.py           System/user prompt templates
    schemas.py           Structured JSON output models
  db/
    duckdb_runner.py     DuckDB connection wrapper
    sql_safety.py        Read-only SQL validation
    schema_introspect.py Schema introspection helpers
  gateway/
    sql_gateway.py       SQL validation + execution + error classification
  evals/
    runner.py            Benchmark runner + answer evaluation
    metrics.py           Metric computation
    report.py            Comparison report generation
  tracing/
    events.py            Trace event schemas + JSONL writer
```

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| DuckDB, not Postgres | Zero-infra local setup, analytical SQL performance |
| sqlglot for SQL parsing | Battle-tested SQL parser/normalizer for Phase 3+ |
| Pydantic v2 for schemas | Structured outputs, model validation, JSON serialization |
| Typer for CLI | Rich terminal output, composable commands |
| JSONL traces | Append-only, easy to grep/index |
| Temperature 0 | Reproducible benchmarks |

## Trade-offs

| Decision | Trade-off |
|----------|-----------|
| DuckDB over Postgres | Simpler setup but loses concurrent agent scenarios |
| String timestamps | Intentional trap but brittle for real date ops |
| Deterministic failure classification | Covers 80% of errors but misses nuanced failures |
| gpt-5.4-mini over full GPT | Lower cost but potentially lower SQL quality |
