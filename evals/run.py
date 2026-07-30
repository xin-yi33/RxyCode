"""Thin wrapper so ``python -m evals.run`` works.

All CLI logic lives in :mod:`evals.runner`; this module just re-exports
``main`` so that the ``-m`` flag finds a runnable module.

Adapted from OpenHands (MIT) evaluation/ runner pattern.
"""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
