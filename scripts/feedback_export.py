"""Operator export for the feedback library — direct DB, no API session.

    RXYCODE_WEB_DATABASE_URL=postgresql+psycopg://... \
        python scripts/feedback_export.py --batch 3            # FB-0003.md
        python scripts/feedback_export.py --open               # current open batch
        python scripts/feedback_export.py --all --out exports/ # every batch

Same Markdown shape as GET /admin/feedback/batches/{seq}/export?format=md:
batch header → stat tables → per-module sections with untrusted bodies in
escaped text fences. Writes one file per batch next to --out (default cwd).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "rxycode-server" / "src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from rxycode_server.feedback.export import batch_payload, export_markdown  # noqa: E402
from rxycode_server.feedback.service import batch_label  # noqa: E402
from rxycode_server.persistence.models import FeedbackBatch  # noqa: E402


def _batches(db: Session, args: argparse.Namespace) -> list[FeedbackBatch]:
    query = select(FeedbackBatch).order_by(FeedbackBatch.seq)
    if args.batch:
        query = query.where(FeedbackBatch.seq == args.batch)
    elif args.open:
        query = query.where(FeedbackBatch.status == "open")
    return list(db.scalars(query))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export feedback batches to Markdown")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", type=int, help="export one batch by seq (FB-NNNN)")
    group.add_argument("--open", action="store_true", help="export the open batch")
    group.add_argument("--all", action="store_true", help="export every batch")
    parser.add_argument("--out", type=Path, default=Path.cwd(), help="output directory")
    args = parser.parse_args()

    url = os.environ.get("RXYCODE_WEB_DATABASE_URL", "").strip()
    if not url:
        print("RXYCODE_WEB_DATABASE_URL is not set", file=sys.stderr)
        return 2

    engine = create_engine(url, poolclass=NullPool)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        with Session(engine) as db:
            batches = _batches(db, args)
            if not batches:
                print("no batches matched", file=sys.stderr)
                return 1
            for batch in batches:
                payload = batch_payload(db, batch)
                path = args.out / f"{batch_label(int(batch.seq))}.md"
                path.write_text(export_markdown(payload), encoding="utf-8")
                print(f"{batch_label(int(batch.seq))}: {payload['item_count']} items -> {path}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
