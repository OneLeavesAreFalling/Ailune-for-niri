"""Entry point for the Ailune pet shell.

The bootstrap step must run before gi.repository loads libwayland so that
gtk4-layer-shell is preloaded in the right order.
"""

from __future__ import annotations

import sys

from .bootstrap import ensure_layer_shell


def main() -> int:
    ensure_layer_shell()
    from .shell import main as shell_main

    return shell_main()


if __name__ == "__main__":
    sys.exit(main())
