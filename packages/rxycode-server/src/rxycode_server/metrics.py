"""Business metrics for the web surface: per-run cost + trace summaries.

The summaries read the SAME durable rows the billing spine wrote —
``usage_records`` is the ledger of record, ``run_events`` carries the
``telemetry.span`` payloads (rxycode_worker.telemetry) plus the provider's
``event/agent_done`` token snapshot.  Everything is tenant-scoped by
construction: callers pass the authenticated tenant id and every query is
filtered on it, so a user sees summaries of their own traces only.

A run with abnormal cost is surfaced verbatim — never averaged into
silence — and the ledger/provider token comparison is shown per run so a
drift between what the provider reported and what was billed is visible.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Run, UsageRecord
from rxycode_server.usage.service import usage_cost_kind

#: A billed amount above this is abnormal and must be surfaced — the same
#: threshold the eval report gate uses (evals/web/report.py).
ABNORMAL_COST_USD = Decimal("1.0")

_SPAN_EVENT = "telemetry.span"
_AGENT_DONE = "event/agent_done"
_USAGE_UPDATED = "usage.updated"


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def _usage_rows(database_url: str, tenant_id: str) -> list[UsageRecord]:
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            return list(
                db.scalars(
                    select(UsageRecord)
                    .join(Run, Run.id == UsageRecord.run_id)
                    .where(Run.tenant_id == tenant_id)
                ).all()
            )
    finally:
        engine.dispose()


def _usage_row(database_url: str, run_id: str) -> UsageRecord | None:
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            return db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == run_id)
            ).first()
    finally:
        engine.dispose()


def _abnormal(amount: str | None) -> bool:
    try:
        return Decimal(str(amount or "0")) > ABNORMAL_COST_USD
    except Exception:
        return False


def _is_span_payload(payload: dict[str, Any]) -> bool:
    return isinstance(payload, dict) and bool(payload.get("trace_id"))


def _agent_done_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The provider's own usage statement: the last agent_done payload."""
    snapshot: dict[str, Any] = {"tokens_used": 0, "budget_used": 0}
    seq = 0
    for event in events:
        if event.get("type") == _AGENT_DONE:
            payload = event.get("payload") or {}
            snapshot = {
                "tokens_used": int(payload.get("tokens_used") or 0),
                "budget_used": int(payload.get("budget_used") or 0),
                "agent_id": str(payload.get("agent_id") or ""),
            }
            seq = int(event.get("seq") or 0)
    snapshot["seq"] = seq
    return snapshot


def _cache_stats(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the cache counters recorded on span attrs."""
    hits = 0
    misses = 0
    for span in spans:
        attrs = span.get("attrs") or {}
        hits += int(attrs.get("cache.hits") or 0)
        misses += int(attrs.get("cache.misses") or 0)
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": (hits / total) if total else 0.0,
    }


def _layers(spans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for span in spans:
        kind = str(span.get("kind") or "internal")
        slot = out.setdefault(kind, {"count": 0, "duration_ms": 0.0})
        slot["count"] += 1
        slot["duration_ms"] = round(
            slot["duration_ms"] + float(span.get("duration_ms") or 0.0), 3
        )
    return out


def _public_span(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": span.get("trace_id"),
        "span_id": span.get("span_id"),
        "parent_span_id": span.get("parent_span_id"),
        "run_id": span.get("run_id"),
        "tool_call_id": span.get("tool_call_id"),
        "name": span.get("name"),
        "kind": span.get("kind"),
        "otel_kind": span.get("otel_kind"),
        "status": span.get("status"),
        "detail": span.get("detail"),
        "duration_ms": span.get("duration_ms"),
        "start_epoch": span.get("start_epoch"),
        "end_epoch": span.get("end_epoch"),
        "attrs": dict(span.get("attrs") or {}),
    }


def run_trace_summary(
    database_url: str, *, tenant_id: str, run_id: str
) -> dict[str, Any]:
    """One run's trace: correlated spans + ledger + provider snapshot.

    Tenant-scoped by the same ``replay`` filter the SSE endpoint uses — a
    foreign tenant sees ``RUN_NOT_FOUND``, never the spans.
    """
    from rxycode_server.events.store import replay

    result = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)
    if result.get("code"):
        return {
            "code": result["code"],
            "run_id": run_id,
            "trace_id": None,
            "spans": [],
            "layers": {},
        }
    events = list(result.get("events") or [])
    raw_spans = [
        event["payload"]
        for event in events
        if event.get("type") == _SPAN_EVENT and _is_span_payload(event.get("payload") or {})
    ]
    spans = [_public_span(span) for span in raw_spans]
    trace_ids = sorted({str(span["trace_id"]) for span in spans})
    epochs = [
        float(span["end_epoch"] or 0.0) - float(span["start_epoch"] or 0.0)
        for span in spans
    ]
    provider = _agent_done_snapshot(events)
    row = _usage_row(database_url, run_id)
    ledger: dict[str, Any] | None = None
    if row is not None:
        ledger = {
            "tokens": int(row.tokens),
            "amount": row.amount,
            "currency": row.currency,
            "price_version": row.price_version,
            "model_id": row.model_id,
            "cost_kind": usage_cost_kind(row.price_version),
            "usage_record_id": row.id,
        }
    usage_events = [
        dict(event.get("payload") or {})
        for event in events
        if event.get("type") == _USAGE_UPDATED
    ]
    ledger_tokens = int(ledger["tokens"]) if ledger else 0
    provider_tokens = int(provider.get("tokens_used") or 0)
    amount = str(ledger["amount"]) if ledger else "0"
    return {
        "code": None,
        "run_id": run_id,
        "events_url": f"/api/v1/runs/{run_id}/events",
        "trace_id": trace_ids[0] if trace_ids else None,
        "trace_ids": trace_ids,
        "span_count": len(spans),
        "spans": spans,
        "layers": _layers(spans),
        "duration_ms": round(sum(epochs) * 1000.0, 3),
        "provider": provider,
        "ledger": ledger or {},
        "usage_events": usage_events,
        "aligned": ledger is not None and ledger_tokens == provider_tokens,
        "token_delta": ledger_tokens - provider_tokens,
        "cache": _cache_stats(spans),
        "cost": {
            "amount": amount,
            "currency": "USD",
            "abnormal": _abnormal(amount),
            "threshold_usd": str(ABNORMAL_COST_USD),
        },
    }


def tenant_cost_metrics(database_url: str, tenant_id: str) -> dict[str, Any]:
    """Per-run cost lines + totals for the tenant's usage ledger.

    Each line reconciles the ledger row against the provider's
    ``agent_done`` snapshot; abnormal runs are listed verbatim in
    ``abnormal`` AND still counted in ``totals`` — surfaced, not averaged
    away; drift between ledger and provider tokens lands in ``mismatches``.
    """
    from rxycode_server.events.store import replay

    rows = _usage_rows(database_url, tenant_id)
    runs: list[dict[str, Any]] = []
    abnormal: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    total_tokens = 0
    total_amount = Decimal("0")
    for row in sorted(rows, key=lambda r: r.run_id):
        provider_tokens = 0
        result = replay(
            database_url, tenant_id=tenant_id, run_id=row.run_id, after_seq=0
        )
        if not result.get("code"):
            provider = _agent_done_snapshot(list(result.get("events") or []))
            provider_tokens = int(provider.get("tokens_used") or 0)
        tokens = int(row.tokens)
        amount = str(row.amount)
        is_abnormal = _abnormal(amount)
        aligned = tokens == provider_tokens
        runs.append(
            {
                "run_id": row.run_id,
                "model_id": row.model_id,
                "tokens": tokens,
                "amount": amount,
                "currency": row.currency,
                "price_version": row.price_version,
                "cost_kind": usage_cost_kind(row.price_version),
                "provider_tokens": provider_tokens,
                "aligned": aligned,
                "abnormal": is_abnormal,
            }
        )
        if is_abnormal:
            abnormal.append(
                {
                    "run_id": row.run_id,
                    "amount": amount,
                    "currency": row.currency,
                    "reason": f"amount exceeds {ABNORMAL_COST_USD} USD threshold",
                }
            )
        if not aligned:
            mismatches.append(
                {
                    "run_id": row.run_id,
                    "ledger_tokens": tokens,
                    "provider_tokens": provider_tokens,
                }
            )
        total_tokens += tokens
        total_amount += Decimal(amount)
    return {
        "tenant_id": tenant_id,
        "run_count": len(runs),
        "runs": runs,
        "totals": {
            "tokens": total_tokens,
            "amount": format(total_amount.quantize(Decimal("0.00000001")), "f"),
            "currency": "USD",
        },
        "abnormal": abnormal,
        "mismatches": mismatches,
    }
