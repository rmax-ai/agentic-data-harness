# Roadmap

## v0.1.0 — MVP ✅

- [x] Repo skeleton, CLI, config loader
- [x] DuckDB dataset generator (3 domains, intentional traps)
- [x] 16 benchmark tasks with expected answers
- [x] Raw SQL agent loop (OpenAI gpt-5.4-mini, structured JSON, trace logging)
- [x] Read-only SQL validation
- [x] Error classification (deterministic)
- [x] Answer evaluation (numeric, exact, set)
- [x] JSONL trace logging
- [x] Baseline raw mode run — 8/16 (50%)

## v0.2.0 — Fingerprint + Cache ✅

- [x] SQL fingerprinting (Level 1: raw hash, Level 2: sqlglot-normalized)
- [x] Query cache table (in-memory DuckDB)
- [x] Cache hit/miss tracing
- [x] Cached mode benchmark run — 8/16 (50%, no cross-task hits in 16-task set)

## v0.3.0 — Corrective Memory ✅

- [x] Failure classifier — 7 deterministic error types (why_not.py)
- [x] Why-not feedback generator — column suggestions, sample values, date ranges
- [x] Corrective memory table (DuckDB, dedup, confidence tracking)
- [x] Memory distiller — feedback → memory entries
- [x] Memory retrieval + injection into agent context
- [x] Cached+memory mode benchmark run — 8/16 (50%)
- [x] 3-mode comparison report (markdown + JSON)

## v0.4.0 — Production Polish

- [ ] File-backed cache (persist across runs)
- [ ] Cost tracking (tiktoken token counting)
- [ ] Failure mode aggregation in comparison report
- [ ] Full 60-task benchmark run
- [ ] Publishable analysis (metrics notebook or article)
- [ ] CI/CD pipeline (GitHub Actions)

## Future

- [ ] Structural fingerprint (Level 3 — AST normal form)
- [ ] Model-assisted failure classification (LLM classifier for edge cases)
- [ ] Multi-model comparison (nano vs mini vs full, non-OpenAI)
- [ ] Adversarial task generation
- [ ] Streaming trace visualization
- [ ] Cross-run cache/memory persistence with schema-hash invalidation
