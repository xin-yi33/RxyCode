"""Entry point so ``python -m evals.run ...`` works.

Delegates to evals.run:main. Kept minimal on purpose — all CLI logic
lives in evals/run.py so it can be unit-tested without subprocess.
"""

from __future__ import annotations

import sys


def main() -> int:
    # ``python -m evals.run`` imports this module as ``__main__`` with
    # sys.argv[0] pointing at evals/run.py; forward to run.main().
    from .run import main as run_main

    return run_main()


if __name__ == "__main__":
    sys.exit(main())
