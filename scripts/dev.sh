#!/usr/bin/env bash
# Development launcher: isolated XDG directories, core + AI service + pet, then UI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ROOT="${AILUNE_DEV_ROOT:-$ROOT/.local}"
mkdir -p "$DEV_ROOT"/{config,data,runtime,cache,xdgconfig,xdgdata,xdgcache}

export AILUNE_ROOT="$ROOT"
export AILUNE_CONFIG_DIR="$DEV_ROOT/config"
export AILUNE_DATA_DIR="$DEV_ROOT/data"
export AILUNE_RUNTIME_DIR="$DEV_ROOT/runtime"
export AILUNE_CACHE_DIR="$DEV_ROOT/cache"
export AILUNE_CONFIG_FILE="$DEV_ROOT/config/config.json"
export XDG_CONFIG_HOME="$DEV_ROOT/xdgconfig"
export XDG_DATA_HOME="$DEV_ROOT/xdgdata"
export XDG_CACHE_HOME="$DEV_ROOT/xdgcache"
export PYTHONPATH="$ROOT/python${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$ROOT/build/ailune" ]]; then
  make -C "$ROOT" build
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Python environment missing. Run ./scripts/setup.sh first." >&2
  exit 1
fi

"$ROOT/build/ailune" run &
CORE_PID=$!
cleanup() {
  kill "$CORE_PID" 2>/dev/null || true
  wait "$CORE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait briefly for the authenticated control API before opening the UI.
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8766/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$CORE_PID" 2>/dev/null; then
    echo "Ailune core exited before the API became ready." >&2
    exit 1
  fi
  sleep 0.2
done

if [[ "${1:-}" == "--no-ui" ]]; then
  echo "Running headless. Press Ctrl+C to stop."
  wait "$CORE_PID"
else
  "$ROOT/.venv/bin/python" -m ailune.ui
fi
