#!/usr/bin/env bash
# Set up the Ailune development environment on Arch Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Ailune setup =="
missing=()
for cmd in go uv curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing+=("$cmd")
  fi
done
if ((${#missing[@]})); then
  echo "Missing commands: ${missing[*]}" >&2
  echo "Install them with pacman (for example: sudo pacman -S go uv curl)." >&2
  exit 1
fi

echo "-- Checking GTK4 layer shell and WebKitGTK (needed by the pet) --"
if ! pkg-config --exists gtk4-layer-shell-0 2>/dev/null; then
  echo "gtk4-layer-shell development files were not found." >&2
  echo "Install: sudo pacman -S gtk4-layer-shell" >&2
  exit 1
fi
if ! pkg-config --exists webkitgtk-6.0 2>/dev/null; then
  echo "WebKitGTK 6.0 development files were not found." >&2
  echo "Install: sudo pacman -S webkitgtk-6.0 python-gobject" >&2
  exit 1
fi
if ! python3 -c "import gi; gi.require_version('Gtk4LayerShell','1.0')" >/dev/null 2>&1; then
  echo "PyGObject cannot import Gtk4LayerShell. Install gtk4-layer-shell and python-gobject." >&2
  exit 1
fi

echo "-- Creating Python virtualenv (system site packages for PyGObject) --"
SYSTEM_PYTHON="$(command -v python3)"
if [[ ! -x .venv/bin/python ]]; then
  # Use the same interpreter that already imports PyGObject; a uv-managed
  # Python would not see the system gi typelibs.
  uv venv --python "$SYSTEM_PYTHON" --system-site-packages .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
export UV_CACHE_DIR="$ROOT/.cache/uv"
uv pip install --quiet fastapi uvicorn httpx PyQt6 pytest

echo "-- Building the Go core --"
mkdir -p build
GOCACHE="$ROOT/.cache/go-build" go build -trimpath -o build/ailune ./cmd/ailune

echo "-- Checking Python imports --"
python - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("WebKit", "6.0")
import fastapi, httpx, uvicorn
import PyQt6
print("Python, GTK4, layer shell, WebKitGTK and PyQt6 look good.")
PY

cat <<'TXT'

Setup complete.

  make run       # core + AI service + pet + settings UI
  make doctor    # environment diagnostics
  make test      # Go and Python tests

The development launcher keeps its data in .local/ so it will not touch your
normal Ailune configuration.
TXT
