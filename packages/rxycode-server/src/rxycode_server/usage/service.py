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


def upsert_terminal_usage(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    model_id: str,
    price_version: str,
    tokens: int,
    event_id: str,
    attribution: list[dict] | None = None,
    recompute: object = None,
) -> dict[str, object]:
    """Run-level aggregate write for the worker finalize path.

    The drain recomputes the WHOLE run's spend (sum over attempts) and must
    land exactly that total — unlike ``record_terminal_usage``, which is
    insert-once per (model, price) for API callers. A prior attempt can
    commit a partial ledger and crash before the terminal write (audit
    r12): with rows present, this reconciles the aggregate via the same
    largest-row-absorb rule as ``adjust_terminal_usage`` (never shrinks);
    with none, it inserts the single aggregate row.

    ``recompute`` is an optional ``() -> (tokens, attributions)`` callback
    invoked while this transaction holds the run row lock. ``append_event``
    serializes on that same row, so a metering read taken HERE cannot be
    overtaken by an in-flight delta commit the way a pre-transaction
    aggregate is (audit r15) — the last ledger writer converges. A fresh
    total only ever raises the passed floor."""
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
            if recompute is not None:
                try:
                    fresh_total, fresh_attr = recompute()
                except Exception:
                    fresh_total, fresh_attr = 0, None
                if int(fresh_total or 0) > int(tokens):
                    tokens = int(fresh_total)
                if fresh_attr:
                    attribution = list(fresh_attr)
            rows = db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == run.id)
            ).all()
            if not rows:
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
                        **({"attribution": attribution} if attribution else {}),
                    },
                )
                db.commit()
                return _public(row)
            existing_total = sum(int(r.tokens) for r in rows)
            target = max(rows, key=lambda r: int(r.tokens))
            if int(tokens) > existing_total:
                others = existing_total - int(target.tokens)
                target.tokens = int(tokens) - others
                target.amount = _amount(target.tokens, target.price_version)
                _add_event(
                    db,
                    run,
                    {
                        "model_id": target.model_id,
                        "price_version": target.price_version,
                        "tokens": int(target.tokens),
                        "currency": "USD",
                        "amount": target.amount,
                        "event_id": event_id,
                        "reconciled": True,
                        "run_total": int(tokens),
                        **({"attribution": attribution} if attribution else {}),
                    },
                )
                db.commit()
            elif attribution:
                # No token increase needed — but the uncertainty marker must
                # still ride the durable log atomically with the ledger state
                # (audit r14).
                _add_event(
                    db,
                    run,
                    {
                        "model_id": target.model_id,
                        "price_version": target.price_version,
                        "tokens": int(target.tokens),
                        "currency": "USD",
                        "amount": target.amount,
                        "event_id": event_id,
                        "reconciled": False,
                        "run_total": int(existing_total),
                        "attribution": attribution,
                    },
                )
                db.commit()
            return _public(target)
    finally:
        engine.dispose()


def adjust_terminal_usage(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    tokens: int,
    event_id: str,
    attribution: list[dict] | None = None,
    recompute: object = None,
) -> dict[str, object] | None:
    """Reconcile an already-committed ledger when late metering arrives.

    ``record_terminal_usage`` is insert-once: a retried run can finalize a
    small ledger before a crashed attempt's spooled ``usage.delta`` replays
    (audit r9). This recomputes against the existing row — a larger total
    raises the ledger and journals ``usage.updated``; a smaller/equal total
    is a no-op so reconciliation never shrinks confirmed spend. Returns
    ``None`` when no ledger row exists yet (the eventual terminal writer
    aggregates the journaled delta itself).

    ``recompute`` has the same under-lock semantics as in
    ``upsert_terminal_usage`` (audit r15)."""
    if tokens < 0 or not event_id:
        raise UsageForbidden()
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                raise UsageForbidden()
            if recompute is not None:
                try:
                    fresh_total, fresh_attr = recompute()
                except Exception:
                    fresh_total, fresh_attr = 0, None
                if int(fresh_total or 0) > int(tokens):
                    tokens = int(fresh_total)
                if fresh_attr:
                    attribution = list(fresh_attr)
            rows = db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == run.id)
            ).all()
            if not rows:
                return None
            existing_total = sum(int(r.tokens) for r in rows)
            if int(tokens) <= existing_total:
                target = max(rows, key=lambda r: int(r.tokens))
                if attribution:
                    # Ledger already covers the total — but ambiguous legacy
                    # attribution still needs a durable atomic marker (r14).
                    _add_event(
                        db,
                        run,
                        {
                            "model_id": target.model_id,
                            "price_version": target.price_version,
                            "tokens": int(target.tokens),
                            "currency": "USD",
                            "amount": target.amount,
                            "event_id": event_id,
                            "reconciled": False,
                            "run_total": int(existing_total),
                            "attribution": attribution,
                        },
                    )
                    db.commit()
                return _public(target)
            # 多 (model, price) 行场景：让最大行吸收「新总量 − 其余行之
            # 和」，而不是把整量写进一行——否则其他行与整量并存会重复
            # 计账（audit r10）。
            target = max(rows, key=lambda r: int(r.tokens))
            others = existing_total - int(target.tokens)
            target.tokens = int(tokens) - others
            target.amount = _amount(target.tokens, target.price_version)
            _add_event(
                db,
                run,
                {
                    "model_id": target.model_id,
                    "price_version": target.price_version,
                    "tokens": int(target.tokens),
                    "currency": "USD",
                    "amount": target.amount,
                    "event_id": event_id,
                    "reconciled": True,
                    "run_total": int(tokens),
                    **({"attribution": attribution} if attribution else {}),
                },
            )
            db.commit()
            return _public(target)
    finally:
        engine.dispose()
