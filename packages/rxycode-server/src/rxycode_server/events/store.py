"""Append an event and its outbox row in one transaction, then replay by seq."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Outbox, Run, RunEvent


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def _session(database_url: str) -> tuple[object, Session]:
    engine = _engine(database_url)
    return engine, Session(engine)


def append_event(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    event_type: str,
    payload: dict,
) -> int:
    """Assign the next seq and write the event plus outbox before returning."""
    engine, db = _session(database_url)
    try:
        run = db.execute(
            select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
        ).scalar_one()
        retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
        seq = max(int(run.event_seq or 0), int(retained or 0)) + 1
        run.event_seq = seq
        event_id = uuid.uuid4().hex
        db.add(
            RunEvent(
                event_id=event_id,
                run_id=run.id,
                tenant_id=tenant_id,
                seq=seq,
                type=event_type,
                payload=payload,
                at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        db.add(Outbox(id=uuid.uuid4().hex, event_id=event_id, dispatch_status="pending", attempts=0))
        db.commit()
        return seq
    finally:
        db.close()
        engine.dispose()


def replay(database_url: str, *, tenant_id: str, run_id: str, after_seq: int) -> dict:
    """Return seqs after the cursor, or CURSOR_EXPIRED when the gap was pruned."""
    engine, db = _session(database_url)
    try:
        run = db.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
        if run is None:
            return {"code": "RUN_NOT_FOUND", "events": []}
        rows = db.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ).all()
        high = int(run.event_seq or 0)
        oldest = int(rows[0].seq) if rows else None
        if after_seq < high and (oldest is None or after_seq + 1 < oldest):
            return {
                "code": "CURSOR_EXPIRED",
                "snapshot_seq": oldest if oldest is not None else high,
                "events": [],
            }
        events = [
            {"seq": int(row.seq), "type": row.type, "payload": dict(row.payload)}
            for row in rows
            if int(row.seq) > after_seq
        ]
        return {"code": None, "events": events}
    finally:
        db.close()
        engine.dispose()


def prune_through(database_url: str, *, tenant_id: str, run_id: str, through_seq: int) -> None:
    """Drop retained events at or below a seq. Later cursors must not skip ahead."""
    engine, db = _session(database_url)
    try:
        run = db.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
        if run is None:
            return
        stale = db.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq <= through_seq)
        ).all()
        stale_ids = [row.event_id for row in stale]
        if stale_ids:
            db.query(Outbox).filter(Outbox.event_id.in_(stale_ids)).delete(synchronize_session=False)
            db.query(RunEvent).filter(RunEvent.event_id.in_(stale_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
        engine.dispose()
