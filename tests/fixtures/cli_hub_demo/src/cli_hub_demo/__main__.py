"""Fixture CLI: one-shot print, or --serve until SIGTERM."""

from __future__ import annotations

import sys
import time


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--serve" in args:
        while True:
            time.sleep(0.2)
    print("cli-hub-demo", " ".join(args), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
