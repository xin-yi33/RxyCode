"""Fail the release gate unless three-platform metadata binds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver.release import ReleaseService


def main() -> int:
    info = ReleaseService().compatibility()
    if not info.get("compatible"):
        print("BIND_FAIL", info)
        return 2
    print("BIND_OK", info["protocol_version"], info["appserver_version"], info["schema_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
