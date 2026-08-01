"""Alias entry point: ``python -m evals.cli`` mirrors ``python -m evals.run``."""

from __future__ import annotations

from .runner import main

if __name__ == "__main__":
    import sys

    sys.exit(main())
