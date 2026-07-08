# Decisions

Design rationale for key choices in agentic-data-harness.

## Major assumptions

1. Cheap models (gpt-5.4-mini) are viable for structured SQL generation with proper infrastructure
2. Deterministic error classification covers 80%+ of failure modes
3. Query cache + corrective memory can measurably reduce speculative waste
4. DuckDB is sufficient for analytical workloads; Postgres adds complexity without benefit for v1

## Key decisions

### DuckDB over Postgres
**Chosen:** DuckDB
**Rationale:** Zero-infra local setup, columnar analytical SQL, fast aggregate queries. No Docker, no connection strings, no migration management.
**Rejected:** Postgres — operational overhead for a benchmark harness. Neon/Dolt — adds branching complexity we don't need yet.

### sqlglot for SQL parsing
**Chosen:** sqlglot (30+ dialects, Python-native)
**Rationale:** Best-maintained SQL parser for Python. Normalization, fingerprinting, and structural extraction all supported.
**Rejected:** sqlparse — too basic (no AST). moz-sql-parser — unmaintained.

### Pydantic v2 for schemas
**Chosen:** Pydantic v2 with strict mode
**Rationale:** Structured output validation, JSON serialization, model_dump, model_validate. Type-safe trace events.
**Rejected:** dataclasses — no validation. TypedDict — no runtime checking.

### json_object response format (not structured outputs)
**Chosen:** `response_format={"type": "json_object"}` 
**Rationale:** Works with gpt-5.4-mini. Structured outputs (strict JSON schema) requires gpt-4o or higher tiers.
**Rejected:** Structured outputs API — not available on mini models.

### Temperature 0
**Chosen:** temperature=0 for all benchmark runs
**Rationale:** Reproducibility is more important than creative SQL generation. We want to measure infrastructure effects, not sampling variance.

### Read-only SQL enforcement
**Chosen:** Prefix-based allowlist (SELECT, WITH, DESCRIBE, SHOW, PRAGMA)
**Rationale:** Simple, deterministic, no AST parsing needed. Catches 99% of dangerous queries.
**Rejected:** AST-based enforcement — more accurate but overengineered for v1.

## Known limitations

- String timestamps are intentionally brittle (traps) but limit real date operations
- Deterministic error classification misses nuanced failures (wrong join semantics, semantic errors)
- DuckDB connection is not thread-safe for concurrent agent runs
- No cost tracking yet (tiktoken installed but cost estimation deferred to Phase 6)
- 16 tasks (one extra over spec, kept as bonus coverage)
