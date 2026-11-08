#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
GOCACHE="$ROOT/.cache/go-build" go test ./...
cd python
"$ROOT/.venv/bin/python" -m pytest -q
