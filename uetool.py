#!/usr/bin/env python3
"""Python entry point for uetool. Invoked by the platform launchers (uetool /
uetool.cmd). Adds this directory to sys.path so `import core` works regardless of
the current working directory, then dispatches to the CLI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.version_info < (3, 11):
    raise SystemExit(
        f"uetool needs Python 3.11+ (uses stdlib tomllib); this is {sys.version.split()[0]}. "
        "Point UETOOL_PYTHON at a 3.11+ interpreter (e.g. UETOOL_PYTHON=python3.13)."
    )

from core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
