# Roadmap

## v0.1.0 — MVP (current)

- [x] Repo skeleton, CLI, config loader
- [x] DuckDB dataset generator (3 domains, intentional traps)
- [x] 16 benchmark tasks with expected answers
- [x] Raw SQL agent loop (OpenAI, structured JSON, trace logging)
- [x] Read-only SQL validation
- [x] Error classification (deterministic)
- [x] Answer evaluation (numeric, exact, set)
- [x] JSONL trace logging
- [ ] Baseline raw mode run

## v0.2.0 — Fingerprint + Cache

- [ ] SQL fingerprinting (Level 1: raw hash, Level 2: normalized hash)
- [ ] Query cache table (DuckDB)
- [ ] Cache hit/miss tracing
- [ ] Cached mode benchmark run
- [ ] Comparison report: raw vs cached

## v0.3.0 — Corrective Memory

- [ ] Failure classifier (deterministic → model-assisted)
- [ ] Why-not feedback generator
- [ ] Corrective memory table
- [ ] Memory retrieval + injection
- [ ] Memory distiller (post-task)
- [ ] Cached+memory mode benchmark run
- [ ] Full 3-mode comparison report

## v0.4.0 — Production Polish

- [ ] Cost tracking (tiktoken)
- [ ] Full 60-task benchmark
- [ ] Result analysis notebook
- [ ] Publishable report template
- [ ] CI/CD pipeline

## Future

- [ ] Structural fingerprint (Level 3)
- [ ] Model-assisted failure classification
- [ ] Multi-model comparison (nano vs mini vs full)
- [ ] Adversarial task generation
- [ ] Streaming trace visualization
