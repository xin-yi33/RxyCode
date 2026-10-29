"""Platform free-quota grant administration — direct DB, no API session.

    RXYCODE_WEB_DATABASE_URL=postgresql+psycopg://... \
        python scripts/platform_slots.py status      # who holds a slot
        python scripts/platform_slots.py backfill    # grant pre-migration users

``backfill`` is the deterministic repair path for users who registered
BEFORE migration 014 (they never got the registration-time claim): it
walks users in ``created_at`` order and claims open slots via the same
SKIP LOCKED path registration uses. Idempotent — granted users are
skipped, a full slot table is a no-op.

Output is user ids + slot numbers only — never emails, never key
material (this tool neither needs nor reads the platform API key).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "packages" / "rxycode-server" / "src"),
)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from rxycode_server.platform_quota.service import (  # noqa: E402
    backfill_grants,
    slot_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Platform free-quota grant slots")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print slot state as JSON")
    sub.add_parser(
        "backfill",
        help="grant open slots to existing users in created_at order",
    )
    args = parser.parse_args()

    url = os.environ.get("RXYCODE_WEB_DATABASE_URL", "").strip()
    if not url:
        print("RXYCODE_WEB_DATABASE_URL is not set", file=sys.stderr)
        return 2

    engine = create_engine(url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if args.command == "backfill":
                result = backfill_grants(db)
            else:
                result = slot_state(db)
    finally:
        engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
