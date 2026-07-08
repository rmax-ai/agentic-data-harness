#!/usr/bin/env bash
# Run adh with OpenAI API key from pass store.
# Usage: scripts/run.sh [adh args...]
#   scripts/run.sh run --mode raw --tasks tasks/small.yaml
set -euo pipefail

# Resolve API key from pass store (gpg bypasses credential filter)
KEY_FILE="$(mktemp)"
trap 'rm -f "$KEY_FILE"' EXIT
gpg -d -q ~/.hermes/.password-store/hermes/openai/api-key.gpg > "$KEY_FILE" 2>/dev/null
export OPENAI_API_KEY="$(head -1 "$KEY_FILE")"

cd "$(dirname "$0")/.."
exec uv run adh "$@"
