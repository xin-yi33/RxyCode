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


def _usage_rows_for_run(database_url: str, run_id: str) -> list[UsageRecord]:
    """ALL ledger rows for the run — one run may legitimately carry several
    (multiple models or price versions), so callers must never read just
    the first row."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            return list(
                db.scalars(
                    select(UsageRecord).where(UsageRecord.run_id == run_id)
                ).all()
            )
    finally:
        engine.dispose()


def _distinct(rows: list[UsageRecord], field: str) -> str:
    """One value when the rows agree; a comma-joined set when they differ."""
    values = sorted({str(getattr(row, field) or "") for row in rows if getattr(row, field)})
    return ", ".join(values)


def _ledger(rows: list[UsageRecord]) -> dict[str, Any] | None:
    """Aggregate a run's ledger rows into the per-run billing total."""
    if not rows:
        return None
    tokens = sum(int(row.tokens) for row in rows)
    amount = sum(
        (Decimal(str(row.amount or "0")) for row in rows), Decimal("0")
    ).quantize(Decimal("0.00000001"))
    kinds = {usage_cost_kind(str(row.price_version)) for row in rows}
    cost_kind = kinds.pop() if len(kinds) == 1 else "mixed"
    return {
        "tokens": tokens,
        "amount": format(amount, "f"),
        "currency": _distinct(rows, "currency") or "USD",
        "price_version": _distinct(rows, "price_version"),
        "model_id": _distinct(rows, "model_id"),
        "cost_kind": cost_kind,
        "row_count": len(rows),
        "usage_record_id": str(rows[0].id),
        "usage_record_ids": [str(row.id) for row in rows],
    }


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
    provider = _agent_done_snapshot(events)
    ledger = _ledger(_usage_rows_for_run(database_url, run_id))
    # Honest duration accounting: the run's elapsed wall clock is the trace
    # ENVELOPE — min(start_epoch) -> max(end_epoch) across ALL spans. The
    # http/server root ENDS when create_run commits, long before an async
    # worker finishes, so a root-span duration would hide the real elapsed
    # (queue wait + execution + commit). Per-layer durations stay in
    # ``layers`` and summed span durations in ``total_span_work_ms`` —
    # nested spans never double-count as elapsed time.
    if spans:
        starts = [float(span["start_epoch"] or 0.0) for span in spans]
        ends = [float(span["end_epoch"] or 0.0) for span in spans]
        elapsed_ms = max(0.0, (max(ends) - min(starts)) * 1000.0)
    else:
        elapsed_ms = 0.0
    total_span_work_ms = sum(float(span["duration_ms"] or 0.0) for span in spans)
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
        "elapsed_ms": round(elapsed_ms, 3),
        "total_span_work_ms": round(total_span_work_ms, 3),
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
    # A run may carry MULTIPLE ledger rows (several models / price
    # versions): every per-run number below is the SUM over all of that
    # run's rows — tokens, amount, and the abnormal threshold check.
    by_run: dict[str, list[UsageRecord]] = {}
    for row in rows:
        by_run.setdefault(str(row.run_id), []).append(row)
    runs: list[dict[str, Any]] = []
    abnormal: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    total_tokens = 0
    total_amount = Decimal("0")
    for run_id in sorted(by_run):
        group = by_run[run_id]
        provider_tokens = 0
        result = replay(
            database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0
        )
        if not result.get("code"):
            provider = _agent_done_snapshot(list(result.get("events") or []))
            provider_tokens = int(provider.get("tokens_used") or 0)
        tokens = sum(int(row.tokens) for row in group)
        amount_dec = sum(
            (Decimal(str(row.amount or "0")) for row in group), Decimal("0")
        ).quantize(Decimal("0.00000001"))
        amount = format(amount_dec, "f")
        kinds = {usage_cost_kind(str(row.price_version)) for row in group}
        is_abnormal = _abnormal(amount)
        aligned = tokens == provider_tokens
        runs.append(
            {
                "run_id": run_id,
                "model_id": _distinct(group, "model_id"),
                "tokens": tokens,
                "amount": amount,
                "currency": _distinct(group, "currency") or "USD",
                "price_version": _distinct(group, "price_version"),
                "cost_kind": kinds.pop() if len(kinds) == 1 else "mixed",
                "row_count": len(group),
                "provider_tokens": provider_tokens,
                "aligned": aligned,
                "abnormal": is_abnormal,
            }
        )
        if is_abnormal:
            abnormal.append(
                {
                    "run_id": run_id,
                    "amount": amount,
                    "currency": _distinct(group, "currency") or "USD",
                    "reason": f"amount exceeds {ABNORMAL_COST_USD} USD threshold",
                }
            )
        if not aligned:
            mismatches.append(
                {
                    "run_id": run_id,
                    "ledger_tokens": tokens,
                    "provider_tokens": provider_tokens,
                }
            )
        total_tokens += tokens
        total_amount += amount_dec
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
