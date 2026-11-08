"""Preload gtk4-layer-shell before PyGObject loads libwayland.

gtk4-layer-shell must appear before libwayland-client in the dynamic linker
order. Python cannot guarantee that through normal imports, so the pet entry
point re-executes itself with LD_PRELOAD set. This is the same workaround used
by other PyGObject layer-shell applications.
"""

from __future__ import annotations

import ctypes.util
import os
import shutil
import subprocess
import sys

MARKER = "AILUNE_LAYER_SHELL_PRELOADED"


def find_layer_shell() -> str | None:
    candidates = [
        "/usr/lib/libgtk4-layer-shell.so",
        "/usr/lib64/libgtk4-layer-shell.so",
        "/usr/local/lib/libgtk4-layer-shell.so",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    if shutil.which("ldconfig"):
        try:
            proc = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=5, check=False)
            for line in proc.stdout.splitlines():
                if "libgtk4-layer-shell.so" in line and "=>" in line:
                    return line.split("=>", 1)[1].strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return ctypes.util.find_library("gtk4-layer-shell")


def ensure_layer_shell() -> None:
    if os.environ.get(MARKER) or os.environ.get("AILUNE_PET_NO_PRELOAD"):
        return
    if not shutil.which(sys.executable):
        return
    library = find_layer_shell()
    if not library:
        print(
            "ailune-pet: gtk4-layer-shell was not found. Install gtk4-layer-shell.",
            file=sys.stderr,
        )
        return
    preload = os.environ.get("LD_PRELOAD", "")
    if "gtk4-layer-shell" in preload:
        return
    env = os.environ.copy()
    env[MARKER] = "1"
    env["LD_PRELOAD"] = f"{library}:{preload}" if preload else library
    try:
        # Re-enter through the module so relative imports still work. Using
        # sys.argv directly would execute __main__.py as a loose script.
        os.execvpe(sys.executable, [sys.executable, "-m", "ailune.pet", *sys.argv[1:]], env)
    except OSError as exc:
        print(f"ailune-pet: could not preload {library}: {exc}", file=sys.stderr)
