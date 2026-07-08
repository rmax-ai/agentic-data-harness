# agentic-data-harness

A small research harness for measuring speculative waste in data-agent workloads.

The project tests a simple systems claim:

> Data agents do not issue isolated queries. They speculate. Infrastructure should optimize the speculative task tree, not only individual SQL statements.

The harness compares three modes over the same DuckDB benchmark:

1. Raw SQL agent
2. Cached SQL agent
3. Cached SQL agent with corrective memory

It measures success rate, query volume, duplicate plan rate, token cost, failure modes, and memory reuse.

## Quickstart

```bash
# Install
uv sync --extra dev

# Set your API key (required)
# Recommended: use the wrapper script which resolves from pass store
./scripts/run.sh run --mode raw --tasks tasks/small.yaml

# Generate benchmark data
uv run adh init-db
uv run adh generate-data

# Run a baseline
# Option A: wrapper script (resolves key from pass store automatically)
./scripts/run.sh run --mode raw --tasks tasks/small.yaml

# Option B: set env var manually
export OPENAI_API_KEY=sk-...
uv run adh run --mode raw --tasks tasks/small.yaml

# Check a specific task
uv run adh check-task sales_001
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for system design and component diagrams.

## Configuration

Config files in `configs/`:
- `default.yaml` — base configuration
- `model.openai.yaml` — OpenAI model settings
- `benchmark.small.yaml` — 15-task benchmark config
- `benchmark.full.yaml` — 60-task benchmark config

## License

MIT
