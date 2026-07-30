"""Fail a live CI lane before collection when required credentials are absent."""

from __future__ import annotations

import os
from collections.abc import Mapping


REQUIRED_ENV = ("RXYCODE_LIVE_API_KEY",)


def missing_credentials(environ: Mapping[str, str] = os.environ) -> list[str]:
    """Return required live-test variables that are absent or whitespace-only."""
    return [name for name in REQUIRED_ENV if not environ.get(name, "").strip()]


def main() -> int:
    missing = missing_credentials()
    if missing:
        names = ", ".join(missing)
        print(
            "::error title=Missing live test credentials::"
            f"Configure the required repository secret(s): {names}"
        )
        return 2
    print("Live provider credentials are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
