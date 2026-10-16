"""Record terminal model usage once per run, model, and price version."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Outbox, Run, RunEvent, UsageRecord

# Published USD per token. An unknown price version records tokens and charges nothing.
_PRICE_PER_TOKEN = {
    "2026-10": Decimal("0.000002"),
}


class UsageForbidden(Exception):
    """The run is not in this tenant, so nothing is charged."""

    def __init__(self) -> None:
        super().__init__("usage forbidden")
        self.http_status = 403
        self.code = "FORBIDDEN"


def usage_cost_kind(price_version: str) -> str:
    """A published price is confirmed. Anything else is an estimate."""
    return "confirmed" if price_version in _PRICE_PER_TOKEN else "estimate"


def _amount(tokens: int, price_version: str) -> str:
    rate = _PRICE_PER_TOKEN.get(price_version, Decimal("0"))
    value = (Decimal(tokens) * rate).quantize(Decimal("0.00000001"))
    return format(value, "f")


def _public(row: UsageRecord) -> dict[str, object]:
    return {
        "id": row.id,
        "amount": row.amount,
        "tokens": int(row.tokens),
        "price_version": row.price_version,
        "model_id": row.model_id,
    }


def _add_event(db: Session, run: Run, payload: dict) -> None:
    retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
    seq = max(int(run.event_seq or 0), int(retained or 0)) + 1
    run.event_seq = seq
    event_id = uuid.uuid4().hex
    db.add(
        RunEvent(
            event_id=event_id,
            run_id=run.id,
            tenant_id=run.tenant_id,
            seq=seq,
            type="usage.updated",
            payload=payload,
            at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    db.add(Outbox(id=uuid.uuid4().hex, event_id=event_id, dispatch_status="pending", attempts=0))


def record_terminal_usage(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    model_id: str,
    price_version: str,
    tokens: int,
    event_id: str,
) -> dict[str, object]:
    """Insert the ledger row once. A replay returns the first amount and token count."""
    if tokens < 0 or not model_id or not price_version or not event_id:
        raise UsageForbidden()
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                raise UsageForbidden()
            existing = db.scalar(
                select(UsageRecord).where(
                    UsageRecord.run_id == run_id,
                    UsageRecord.model_id == model_id,
                    UsageRecord.price_version == price_version,
                )
            )
            if existing is not None:
                return _public(existing)
            amount = _amount(tokens, price_version)
            row = UsageRecord(
                id=uuid.uuid4().hex,
                run_id=run.id,
                model_id=model_id,
                price_version=price_version,
                tokens=tokens,
                currency="USD",
                amount=amount,
            )
            db.add(row)
            _add_event(
                db,
                run,
                {
                    "model_id": model_id,
                    "price_version": price_version,
                    "tokens": tokens,
                    "currency": "USD",
                    "amount": amount,
                    "event_id": event_id,
                },
            )
            db.commit()
            return _public(row)
    finally:
        engine.dispose()
