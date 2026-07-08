# agentic-data-harness

A small research harness for measuring speculative waste in data-agent workloads.

The project tests a simple systems claim:

> Data agents do not issue isolated queries. They speculate. Infrastructure should optimize the speculative task tree, not only individual SQL statements.

The harness compares three modes over the same DuckDB benchmark:

1. Raw SQL agent
2. Cached SQL agent
3. Cached SQL agent with corrective memory

It measures **success rate** and **memory reuse** across modes. Per-step traces capture query history, error types, cache status, and why-not diagnostics.

## Quickstart

```bash
# Install
uv sync --extra dev

# Set your API key (required — use .envrc or export directly)
#   cp .envrc.example .envrc   # then edit with your key
#   direnv allow
# Or:
#   export OPENAI_API_KEY=sk-your-key-here

# Generate benchmark data (requires a clean database — delete data/duckdb/benchmark.db first if re-running)
rm -f data/duckdb/benchmark.db
uv run adh init-db
uv run adh generate-data

# Run a baseline (16 tasks)
uv run adh run --mode raw --tasks tasks/small.yaml

# Run all three modes and compare
uv run adh run --mode all --tasks tasks/small.yaml
uv run adh compare reports/2026-0*.json

# Check a specific task
uv run adh check-task sales_001
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for system design and component diagrams.

## Configuration

```yaml
# configs/default.yaml — base configuration
# configs/model.openai.yaml — OpenAI model settings
# configs/benchmark.small.yaml — 16-task benchmark config
# configs/benchmark.full.yaml — 60-task benchmark config
```

## License

MIT
