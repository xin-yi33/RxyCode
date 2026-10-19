"""Drain queued web runs: fenced claim -> sandboxed child turn -> commit.

The API writes a durable ``run.created`` row with status ``pending``; nothing
executes it until a worker takes the fenced lease. This module is that worker
for the deployed compose stack (``python -m rxycode_worker.drain``). It runs
in two halves:

* the DRAIN process (this file's normal entry) claims runs, enforces the
  placement/permission gate, spawns the turn INSIDE a per-run kernel sandbox
  (``rxycode_runner.sandbox.userns``: user/pid/ipc/uts namespaces + a minimal
  read-only root + only the run workspace writable), renews the lease with
  deadline-bounded probes, and commits the terminal state.
* the TURN process (this same module re-entered with ``RXYCODE_TURN_RUN_ID``
  set) runs the real ``Session.prompt``/AgentV2 machinery — journaling,
  telemetry spans, the usage ledger inputs, persisted steer delivery — all
  inside the sandbox, so tool execution can never touch the worker host's
  filesystem or another tenant's workspace.

Public-stack rule (the compose default ``RXYCODE_WORKER_EXECUTION=cloud-only``):
only ``cloud:{tenant}:{workspace}`` targets execute, the tenant segment must
equal the run's own tenant, and ``full``/``full_auto`` profiles are refused —
Full authority means unsandboxed host execution, which does not exist here.
``sandboxed-local`` is the development-host mode: ``local:*`` targets are
accepted but STILL confined — a drain never runs a turn unconfined. A host
without userns/bwrap makes the provider fail closed; nothing falls back to
subprocess on the worker host.

Terminal writes go through the fenced ``commit_terminal``/``confirm_cancel``;
a lost lease (``LeaseRejected`` or renewals unproven past the TTL) aborts
honestly — the new owner finishes the run.

Environment (read in ``worker_config_from_env``):
    RXYCODE_WEB_DATABASE_URL   required — the same DSN the API uses
    RXYCODE_WORKER_ID          default ``drain-<hostname>-<pid>``
    RXYCODE_WORKER_POLL_SECONDS      default 2
    RXYCODE_WORKER_LEASE_TTL         default 120 (renewed while a run executes)
    RXYCODE_WORKER_RUN_TIMEOUT       default 900 — a prompt past this is
                                   cancelled and the run commits ``failed``
    RXYCODE_WORKER_WORKSPACES        default /tmp/rxycode-runs — per-tenant
                                   workspace dirs are created under it
    RXYCODE_WORKER_MODEL             optional model name for AgentV2
    RXYCODE_WORKER_EXECUTION         ``cloud-only`` (default) or
                                   ``sandboxed-local`` (dev host opt-in)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_LOG = logging.getLogger(__name__)

_CLAIMABLE = ("pending", "leased", "running", "cancel_requested")
_CLAIMABLE_SQL = "','".join(_CLAIMABLE)

#: The one published ledger price version (``usage.service._PRICE_PER_TOKEN``).
#: Runs executed without provider credentials still record their real (zero)
#: spend under this version so the ledger row is honest, not absent.
_PRICE_VERSION = "2026-10"

_JOURNAL_CAP = 500

#: Projection rows that must survive the intermediate-event cap: a flooded
#: run may lose deltas, but its terminal answer is never dropped (audit r3).
_TERMINAL_PROJECTIONS = frozenset({"assistant.final"})

#: Per-database-call bound inside the lease watchdog. A stalled store cannot
#: stall the watchdog past the lease TTL: each probe is wrapped in wait_for
#: and the monotonic deadline below still expires the turn on time.
_LEASE_IO_BUDGET = 15.0

#: Run statuses from which no further ledger write can come — used by the
#: usage-spool replay to dead-letter a file whose run closed without a
#: UsageRecord (the journaled delta row still preserves the spend).
_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "recovery_required"}
)

#: run.permission_profile -> Session.prompt(permission_mode=...). The durable
#: profile is an opaque string; only real vocabulary maps — anything else
#: falls back to the configured default rather than silently widening.
_PERMISSION_MODE_MAP = {
    "full_auto": "full_auto",
    "full": "full_auto",
    "auto_edit": "auto_edit",
    "confirm_all": "confirm_all",
}

_EXECUTION_MODES = ("cloud-only", "sandboxed-local")

#: The confined turn reports its outcome here (inside the run workspace).
_TURN_RESULT = ".turn-result.json"

#: Environment the confined turn receives. Everything else is stripped by
#: --clearenv — a run never inherits worker secrets it was not granted.
_CHILD_ENV_PASS = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "TERM",
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "RXYCODE_UVLOOP",
    "RXYCODE_WEB_DATABASE_URL",
    "RXYCODE_WORKER_MODEL",
    "RXYCODE_LLM_BASE_URL",
    "RXYCODE_LLM_MODEL",
    "RXYCODE_API_KEY",
)


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    worker_id: str
    poll_seconds: float = 2.0
    lease_ttl: int = 120
    run_timeout: float = 900.0
    workspaces_root: str = "/tmp/rxycode-runs"
    model: str = ""
    execution_mode: str = "cloud-only"


def worker_config_from_env() -> WorkerConfig:
    """Read the drain configuration from the environment."""
    database_url = os.environ.get("RXYCODE_WEB_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RXYCODE_WEB_DATABASE_URL is required")
    worker_id = (
        os.environ.get("RXYCODE_WORKER_ID", "").strip()
        or f"drain-{socket.gethostname()}-{os.getpid()}"
    )
    execution_mode = (
        os.environ.get("RXYCODE_WORKER_EXECUTION", "cloud-only").strip().lower() or "cloud-only"
    )
    return WorkerConfig(
        database_url=database_url,
        worker_id=worker_id,
        poll_seconds=max(0.2, float(os.environ.get("RXYCODE_WORKER_POLL_SECONDS", "2"))),
        lease_ttl=max(10, int(os.environ.get("RXYCODE_WORKER_LEASE_TTL", "120"))),
        run_timeout=max(30.0, float(os.environ.get("RXYCODE_WORKER_RUN_TIMEOUT", "900"))),
        workspaces_root=os.environ.get("RXYCODE_WORKER_WORKSPACES", "/tmp/rxycode-runs"),
        model=os.environ.get("RXYCODE_WORKER_MODEL", "").strip(),
        execution_mode=execution_mode,
    )


def _ledger_model(model: str) -> str:
    """Resolve the ledger's model_id to a real model name, never the "active"
    alias. Reads config only; never touches or logs the api key."""
    if model:
        return model
    try:
        from RxyCode.RxyCode1_1_0.config.settings import (
            get_active_model_config,
            load_config,
        )

        name = str(get_active_model_config(load_config()).get("model_name") or "")
        return name or "active"
    except Exception:
        return "active"


def claimable_run_ids(database_url: str, *, limit: int = 1) -> list[str]:
    """Runs a worker may take: ``pending``, or an active status whose lease
    expired (a dead worker's leftovers). ``claim`` re-checks under FOR UPDATE,
    so a racing claimant simply loses."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id FROM runs
                    WHERE status IN ('{_CLAIMABLE_SQL}')
                      AND (
                        status = 'pending'
                        OR lease_until IS NULL
                        OR lease_until < :now
                      )
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"now": datetime.now(timezone.utc), "limit": int(limit)},
            ).all()
    finally:
        engine.dispose()
    return [str(row[0]) for row in rows]


def run_status(database_url: str, run_id: str) -> str:
    """Current status column — the cancel signal the watchdog polls."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            value = conn.execute(
                text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}
            ).scalar()
    finally:
        engine.dispose()
    return str(value or "")


def _run_identity(database_url: str, run_id: str) -> dict[str, str]:
    """tenant + project + actor + traceparent for the claimed run.

    The RunContext inside the turn is built from these persisted fields —
    never minted fresh and never taken from client claims.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT r.tenant_id, COALESCE(s.project_id, '') "
                    "FROM runs r LEFT JOIN sessions s "
                    "ON s.tenant_id = r.tenant_id AND s.id = r.session_id "
                    "WHERE r.id = :id"
                ),
                {"id": run_id},
            ).one()
            payload = conn.execute(
                text(
                    "SELECT payload FROM run_events "
                    "WHERE run_id = :id AND type = 'run.created' "
                    "ORDER BY seq LIMIT 1"
                ),
                {"id": run_id},
            ).scalar()
    finally:
        engine.dispose()
    payload = payload if isinstance(payload, dict) else {}
    quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
    return {
        "tenant_id": str(row[0]),
        "project_id": str(row[1] or ""),
        "actor_id": str(quota.get("user_id") or ""),
        "traceparent": str(payload.get("traceparent") or ""),
    }


def _agent_done_row(database_url: str, run_id: str) -> tuple[str, int]:
    """(event_id, tokens_used) of the journaled ``event/agent_done`` row.

    ``replay`` dicts drop ``event_id``; the usage ledger needs it, so the row
    is read directly (same query shape as ``evals.web.run._agent_done_event_id``).
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import RunEvent

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with SASession(engine) as db:
            row = db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.type == "event/agent_done")
                .order_by(RunEvent.seq.desc())
                .limit(1)
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return "", 0
    payload = row.payload if isinstance(row.payload, dict) else {}
    tokens = int(payload.get("tokens") or payload.get("tokens_used") or 0)
    return str(row.event_id), tokens


def _lease_epochs(conn: Any, run_id: str) -> list[tuple[int, str]]:
    """``worker.lease`` rows ordered by seq — each claim opens a new lease
    epoch, so an untagged row is attributed to the epoch that was active
    when it committed (audit r8: pre-upgrade completions carry no
    ``attempt`` key and must not fall into a separate summed bucket)."""
    from sqlalchemy import text

    rows = conn.execute(
        text(
            "SELECT seq, payload FROM run_events "
            "WHERE run_id = :id AND type = 'worker.lease' ORDER BY seq"
        ),
        {"id": run_id},
    ).all()
    bounds: list[tuple[int, str]] = []
    for seq, payload in rows:
        if isinstance(payload, dict):
            bounds.append((int(seq), str(payload.get("epoch") or "")))
    return bounds


def _epoch_at_seq(bounds: list[tuple[int, str]], seq: int) -> str:
    """Latest lease epoch whose ``worker.lease`` seq precedes ``seq``;
    ``""`` when the row predates every recorded claim."""
    epoch = ""
    for bound_seq, bound_epoch in bounds:
        if bound_seq > seq:
            break
        epoch = bound_epoch or epoch
    return epoch


def _usage_deltas_by_attempt(database_url: str, run_id: str) -> dict[str, int]:
    """Per-attempt metering that survives a SIGKILLed turn.

    Each confined child heartbeats CUMULATIVE ``usage.delta`` rows tagged
    with its lease epoch; a retried run starts a fresh baseline per attempt.
    Returns ``{attempt: last cumulative total}`` — the caller merges
    sources within an attempt (max) and sums ACROSS attempts (audit r6).

    Untagged legacy rows are ambiguous under interleaved commits (audit
    r9): a delayed epoch-1 delta arriving after epoch 2's claim must not
    inflate epoch 2. Cumulative snapshots are non-decreasing per attempt,
    so an untagged row joins the latest-claimed candidate epoch whose
    bucket it could extend (largest bucket <= the row's value); failing
    that, the earliest claimed candidate — biased to under-count rather
    than double-charge. Rows pre-dating every claim keep the ``""`` bucket."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT seq, payload FROM run_events "
                    "WHERE run_id = :id AND type = 'usage.delta' ORDER BY seq"
                ),
                {"id": run_id},
            ).all()
            bounds = _lease_epochs(conn, run_id)
    finally:
        engine.dispose()
    latest: dict[str, int] = {}
    for seq, payload in rows:
        if not isinstance(payload, dict):
            continue
        tokens = int(payload.get("input_tokens") or 0) + int(payload.get("output_tokens") or 0)
        attempt = str(payload.get("attempt") or "")
        if attempt:
            latest[attempt] = max(latest.get(attempt, 0), tokens)
            continue
        candidates = [e for b_seq, e in bounds if int(b_seq) <= int(seq) and e]
        if candidates:
            ordered = list(dict.fromkeys(candidates))
            eligible = [e for e in ordered if latest.get(e, 0) <= tokens]
            target = max(eligible, key=lambda e: latest.get(e, 0)) if eligible else ordered[0]
        else:
            target = _epoch_at_seq(bounds, int(seq)) or ""
        latest[target] = max(latest.get(target, 0), tokens)
    return latest


def _agent_done_by_attempt(
    database_url: str, run_id: str
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """``event/agent_done`` snapshots grouped by lease epoch — the RunJournal
    tags each row with the attempt that produced it.

    Untagged legacy rows need attribution that cannot double-charge.
    Seq-anchoring mis-binds a delayed epoch-1 completion that commits after
    epoch 2's claim (audit r9); "earliest epoch without a done" overcharges
    when the earlier attempt crashed done-less and the row is epoch 2's own
    completion (audit r10); exact bucket equality still fails when the
    owning attempt's last heartbeat lagged its true total (audit r11:
    e1 metered 5 dead + e2 metered 90 then done 100 -> must not bind e1).
    The disambiguator: a done row's tokens are its attempt's FINAL total,
    so the owning epoch's metered bucket can never exceed it. Among open
    candidates whose bucket fits (``metered <= done``), pick the smallest
    surplus ``done - metered`` — the completion rejoins the attempt it
    least extends. No feasible bucket -> earliest open epoch -> seq-anchor.

    When more than one bucket is feasible the binding is genuinely
    ambiguous (a crashed epoch's lagged meter can sit arbitrarily close
    to a later epoch's final total — audit r12). The choice is still
    min-surplus, but the ambiguity is returned for the caller to journal
    explicitly: a `usage.attribution` row carrying every feasible epoch
    and its bucket, so the ledger never presents an inferred total as if
    it were the only consistent one. Returns ``(buckets, ambiguities)``.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT seq, payload FROM run_events "
                    "WHERE run_id = :id AND type = 'event/agent_done' ORDER BY seq"
                ),
                {"id": run_id},
            ).all()
            # Metered buckets need the sibling stream too — an untagged
            # done row's value equals its own attempt's usage.delta total,
            # which is the only signal separating "delayed epoch-1
            # completion" from "epoch-2's own legacy completion".
            metered = conn.execute(
                text(
                    "SELECT seq, payload FROM run_events "
                    "WHERE run_id = :id AND type = 'usage.delta' ORDER BY seq"
                ),
                {"id": run_id},
            ).all()
            bounds = _lease_epochs(conn, run_id)
    finally:
        engine.dispose()
    metered_by_attempt: dict[str, int] = {}
    for _seq, payload in metered:
        if not isinstance(payload, dict):
            continue
        attempt = str(payload.get("attempt") or "")
        if attempt:
            metered_by_attempt[attempt] = max(
                metered_by_attempt.get(attempt, 0),
                int(payload.get("input_tokens") or 0)
                + int(payload.get("output_tokens") or 0),
            )
    latest: dict[str, int] = {}
    filled: set[str] = set()
    ambiguous: list[dict[str, Any]] = []
    for seq, payload in rows:
        if not isinstance(payload, dict):
            continue
        tokens = int(payload.get("tokens") or payload.get("tokens_used") or 0)
        attempt = str(payload.get("attempt") or "")
        if attempt:
            filled.add(attempt)
            latest[attempt] = max(latest.get(attempt, 0), tokens)
            continue
        candidates = list(
            dict.fromkeys(
                e for b_seq, e in bounds if int(b_seq) <= int(seq) and e
            )
        )
        open_candidates = [e for e in candidates if e not in filled]
        # A done equals its OWN attempt's final metered total, so the owning
        # epoch's bucket can never exceed the row's value. Among feasible
        # buckets pick the smallest surplus — a lagging heartbeat (metered
        # 90, done 100) still rejoins its own epoch instead of stealing an
        # earlier done-less one; an exact match has surplus 0 and wins.
        feasible = [
            e
            for e in open_candidates
            if max(metered_by_attempt.get(e, 0), latest.get(e, 0)) <= tokens
        ]
        target = min(
            feasible,
            key=lambda e: tokens - max(metered_by_attempt.get(e, 0), latest.get(e, 0)),
            default=None,
        )
        if target is None:
            target = open_candidates[0] if open_candidates else (
                _epoch_at_seq(bounds, int(seq)) or ""
            )
        if len(feasible) > 1 or (not feasible and len(candidates) > 1):
            ambiguous.append(
                {
                    "seq": int(seq),
                    "tokens": tokens,
                    "chosen": target,
                    "candidates": {
                        e: max(metered_by_attempt.get(e, 0), latest.get(e, 0))
                        for e in (feasible or candidates)
                    },
                }
            )
        filled.add(target)
        latest[target] = max(latest.get(target, 0), tokens)
    return latest, ambiguous


def _emit_attribution_events(
    database_url: str,
    tenant_id: str,
    run_id: str,
    ambiguities: list[dict[str, Any]],
) -> None:
    """Journal a ``usage.attribution`` row for every ambiguous legacy
    ``agent_done`` binding — explicit uncertainty on the durable log instead
    of an inferred total presented as confirmed (audit r12). Dedupe on the
    source row's seq so retries/replays never pile up duplicate notes."""
    if not ambiguities:
        return
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.events.store import append_event

    seen: set[int] = set()
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload FROM run_events "
                    "WHERE run_id = :id AND type = 'usage.attribution'"
                ),
                {"id": run_id},
            ).all()
        for (payload,) in rows:
            if isinstance(payload, dict):
                try:
                    seen.add(int(payload.get("attribution_seq")))
                except (TypeError, ValueError):
                    continue
    finally:
        engine.dispose()
    for item in ambiguities:
        if int(item.get("seq") or -1) in seen:
            continue
        # Propagate failures: in spool replay the caller keeps the file so
        # the note is retried next pass — a committed ledger must not lose
        # its durable uncertainty marker to a transient error (audit r13).
        append_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="usage.attribution",
            payload={
                **item,
                "attribution_seq": int(item.get("seq") or -1),
                "ambiguous": True,
                "rule": "min-surplus-feasible",
            },
        )


def _run_metering_total(
    database_url: str, run_id: str
) -> tuple[int, list[dict[str, Any]]]:
    """Fresh committed metering view: per-attempt max of journaled
    ``usage.delta`` and ``event/agent_done`` buckets, summed across
    attempts, plus the ambiguity notes the fresh read produced. Passed as
    the usage writer's under-lock ``recompute`` callback — ``append_event``
    serializes on the same run row the ledger transaction holds, so this
    read sees every metering row any committed writer can have produced
    (audit r15)."""
    deltas = _usage_deltas_by_attempt(database_url, run_id)
    dones, attributions = _agent_done_by_attempt(database_url, run_id)
    total = sum(
        max(deltas.get(a, 0), dones.get(a, 0))
        for a in set(deltas) | set(dones)
    )
    return total, attributions


def _usage_spool_dir(workspaces_root: str) -> Path:
    return Path(workspaces_root) / ".sandboxes" / ".usage-spool"


def _spool_streamed_usage(
    spool_dir: Path,
    *,
    tenant_id: str,
    run_id: str,
    epoch: int,
    input_tokens: int,
    output_tokens: int,
    journaled: bool = False,
    model_id: str = "",
    price_version: str = "",
) -> None:
    """Last-resort retention: when the DB cannot take the final
    ``usage.delta`` row, drop the metering on parent-owned disk so a later
    drain pass can replay it — known spend is never silently discarded
    (audit r8). ``model_id``/``price_version`` let replay INSERT a ledger
    on a terminal run whose owner crashed before writing one (audit r15).
    """
    spool_dir.mkdir(parents=True, exist_ok=True)
    path = spool_dir / f"{run_id}.{epoch}.usage.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "attempt": str(epoch),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                **({"journaled": True} if journaled else {}),
                **({"model_id": model_id} if model_id else {}),
                **({"price_version": price_version} if price_version else {}),
            }
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def _ensure_pending_reconcile_spool(
    workspaces_root: str,
    *,
    tenant_id: str,
    run_id: str,
    epoch: int,
    input_tokens: int,
    output_tokens: int,
    journaled: bool = True,
    model_id: str = "",
    price_version: str = "",
) -> None:
    """Drop a pending-reconcile spool so the next drain pass re-runs ledger
    reconciliation (audit r14). ``journaled`` is the caller's statement
    that the metered tokens are already durable ``usage.delta`` rows —
    when an earlier spool write ALSO failed, passing True here would let
    replay recompute from older rows and delete the file without ever
    journaling this spend (audit r15). Never overwrites an existing file:
    a non-journaled spool still owes its delta append."""
    spool_dir = _usage_spool_dir(workspaces_root)
    path = spool_dir / f"{run_id}.{epoch}.usage.json"
    if path.exists():
        return
    _spool_streamed_usage(
        spool_dir,
        tenant_id=tenant_id,
        run_id=run_id,
        epoch=epoch,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        journaled=journaled,
        model_id=model_id,
        price_version=price_version,
    )


def _replay_usage_spool(database_url: str, workspaces_root: str) -> None:
    """Re-attempt every spooled metering write; each file deletes itself on
    success and stays for the next pass on failure."""
    from rxycode_server.events.store import append_event

    spool_dir = _usage_spool_dir(workspaces_root)
    try:
        files = sorted(spool_dir.glob("*.usage.json"))
    except OSError:
        return
    for path in files:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        run_id = str(row.get("run_id") or "")
        if not run_id:
            path.unlink(missing_ok=True)  # malformed file — dead-letter
            continue
        if not row.get("journaled"):
            try:
                append_event(
                    database_url,
                    tenant_id=str(row["tenant_id"]),
                    run_id=run_id,
                    event_type="usage.delta",
                    payload={
                        "input_tokens": int(row.get("input_tokens") or 0),
                        "output_tokens": int(row.get("output_tokens") or 0),
                        "cumulative": True,
                        "attempt": str(row.get("attempt") or ""),
                        "final": True,
                        "spooled": True,
                    },
                )
            except Exception:
                continue  # stays on disk for the next pass
            # Mark journaled so a kept-for-reconcile file does not journal
            # a duplicate delta row on every pass (audit r10). The flag
            # update must be atomic like the initial spool write — an
            # in-place rewrite that is truncated by a crash would leave a
            # malformed file that every later pass silently skips (r11).
            row["journaled"] = True
            try:
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(row), encoding="utf-8")
                tmp.replace(path)
            except OSError:
                pass  # worst case: one duplicate row — max() absorbs it

        # A retry may finalize a smaller ledger BEFORE this spool replays —
        # or AFTER it, computing its total from a stale read (audit r9/r10).
        # ``upsert_terminal_usage`` covers both cases in one locked write:
        # existing rows reconcile up to the recomputed total; a terminal run
        # whose owner crashed BEFORE its first ledger write gets the row
        # inserted here instead of dead-lettering the spend (audit r15).
        # The under-lock recompute additionally folds in any delta that
        # committed between this snapshot and the ledger transaction.
        try:
            total, attributions = _run_metering_total(database_url, run_id)
            if total <= 0:
                # A journaled pending-reconcile spool on a TERMINAL run with
                # a zero recompute has nothing left to converge — dead-letter
                # instead of lingering forever. Non-terminal stays parked.
                try:
                    status = run_status(database_url, run_id)
                except Exception:
                    status = ""
                if row.get("journaled") and status in _TERMINAL_STATUSES:
                    _LOG.warning(
                        "run %s: pending spool on terminal run with zero "
                        "recompute; dead-lettered",
                        run_id,
                    )
                    path.unlink(missing_ok=True)
                continue  # inconsistent — keep for a later pass
            from rxycode_server.usage.service import (
                UsageForbidden,
                upsert_terminal_usage,
            )

            upsert_terminal_usage(
                database_url,
                tenant_id=str(row["tenant_id"]),
                run_id=run_id,
                model_id=str(row.get("model_id") or "unknown"),
                price_version=str(row.get("price_version") or _PRICE_VERSION),
                tokens=total,
                event_id=uuid.uuid4().hex,
                attribution=attributions,
                recompute=lambda rid=run_id: _run_metering_total(
                    database_url, rid
                ),
            )
            _emit_attribution_events(
                database_url, str(row["tenant_id"]), run_id, attributions
            )
        except UsageForbidden:
            # The run/tenant no longer exists — the journaled delta row is
            # durable and nothing can ever reconcile it. Dead-letter.
            _LOG.warning(
                "run %s: spool reconcile forbidden (run/tenant gone);"
                " dropping file", run_id,
            )
        except Exception:
            _LOG.warning(
                "run %s: spool replay ledger reconcile failed; next pass retries",
                run_id,
                exc_info=True,
            )
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _flush_streamed_usage(
    database_url: str,
    tenant_id: str,
    run_id: str,
    epoch: int,
    streamed: dict[str, int],
    deltas: dict[str, int],
) -> bool:
    """Persist metering that arrived over the stderr pipe but never made a
    heartbeat — a killed turn's last-known spend becomes one final durable
    ``usage.delta`` row tagged with THIS attempt's epoch. Runs on every exit
    path (including lost lease): it journals metering, not terminal state,
    so a retry can recover the spend even though this worker must not write
    the terminal status (audit r7). Returns True when the row is durable —
    the caller retries briefly then spools to disk (audit r8)."""
    total = int(streamed.get("tokens") or 0)
    if total <= 0 or total <= deltas.get(str(epoch), 0):
        return True
    try:
        from rxycode_server.events.store import append_event

        append_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="usage.delta",
            payload={
                "input_tokens": int(streamed.get("input_tokens") or 0),
                "output_tokens": int(streamed.get("output_tokens") or 0),
                "cumulative": True,
                "attempt": str(epoch),
                "final": True,
            },
        )
        return True
    except Exception:
        _LOG.warning("run %s: streamed-usage flush failed", run_id, exc_info=True)
        return False


class _RunCancelled(Exception):
    """The run's status flipped to cancel_requested mid-flight."""


class _LeaseRenewalLost(Exception):
    """Lease renewals could not be proven before the TTL expired.

    Distinct from ``LeaseRejected`` (the fence itself said no): here the
    store stopped answering long enough that the lease deadline passed —
    another worker may already own the run. The turn is cancelled and this
    worker steps aside; it never commits a terminal state it cannot prove
    it owns."""


class _UnsupportedTarget(Exception):
    """The run's persisted target_id/placement is refused by this worker.

    The shared worker only executes what the deployment's execution mode
    allows, always inside the per-run sandbox. A ``sandbox:``/unknown target
    or a ``local:``/``full`` placement on the public stack is refused
    honestly rather than silently executed without its requested isolation."""


class _DrainWorkerShim:
    """The minimal worker surface ``agent_events.accept_steer`` needs.

    The stdio worker's ``_handle_steer`` appends to ``_steer_queue`` which
    ``Session.drain_steers`` drains mid-turn; this shim is that channel for a
    run with no stdin client. It answers like the real handler did: a queued
    steer only when a turn is running.
    """

    def __init__(self, run_id: str, session_id: str) -> None:
        self._session_id = session_id
        self._web_run_id = run_id
        self._next_id = 1
        self._steer_queue: list[str] = []
        self._turn: asyncio.Task[Any] | None = None

    async def _handle_steer(self, params: dict[str, Any], request_id: int) -> None:
        text = str(params.get("text") or "").strip()
        if text and self._turn is not None and not self._turn.done():
            self._steer_queue.append(text)

    def _take_steers(self) -> list[str]:
        taken = [str(item).strip() for item in self._steer_queue if str(item).strip()]
        self._steer_queue.clear()
        return taken


def _projection_rows(
    method: str,
    body: dict[str, Any],
    tool_names: dict[str, str],
    *,
    run_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Map one protocol ``event/*`` notification to the event types apps/web's
    ``eventReducer`` consumes. Returns ``(event_type, payload)`` rows — a
    drained run's answer, tool calls and waits must reach the UI projection,
    not only the ``notify.*`` audit rows."""
    rows: list[tuple[str, dict[str, Any]]] = []
    if method == "event/final":
        rows.append(
            (
                "assistant.final",
                {
                    "text": str(body.get("text") or ""),
                    "run_id": str(body.get("run_id") or run_id),
                    "input_tokens": body.get("input_tokens"),
                    "output_tokens": body.get("output_tokens"),
                },
            )
        )
    elif method in ("event/message_delta", "event/progress"):
        rows.append(
            (
                "assistant.delta",
                {
                    "text": str(body.get("text") or ""),
                    "intermediate": bool(body.get("intermediate")) or method == "event/progress",
                },
            )
        )
    elif method == "event/tool_begin":
        call_id = str(body.get("call_id") or "")
        if call_id:
            tool_names[call_id] = str(body.get("tool_name") or "")
    elif method == "event/tool_end":
        call_id = str(body.get("call_id") or "")
        ok = bool(body.get("ok"))
        rows.append(
            (
                "tool.completed" if ok else "tool.failed",
                {
                    "call_id": call_id,
                    "tool": tool_names.get(call_id, ""),
                    "status": str(body.get("status") or ("completed" if ok else "failed")),
                    "summary": str(body.get("summary") or ""),
                },
            )
        )
    elif method == "event/agent_needs_input":
        # The wire's only waiting-for-input signal; the service that journals
        # approval.requested itself isn't reachable in-process, so project
        # both buckets the reducer reads.
        request_id = str(body.get("request_id") or "")
        preview = str(body.get("preview") or "")
        rows.append(("question.requested", {"question_id": request_id, "prompt": preview}))
        rows.append(
            (
                "approval.requested",
                {
                    "approval_id": request_id,
                    "status": "pending",
                    "tool": "",
                    "command": preview,
                },
            )
        )
    elif method == "event/plan":
        # PlanUpdate carries `steps: list[str]` — project each step as a plan
        # item so the reducer's plan bucket renders the real plan.
        steps = body.get("steps")
        if isinstance(steps, list):
            for index, step in enumerate(steps):
                rows.append(
                    (
                        "plan.updated",
                        {
                            "plan_id": f"plan-{index}",
                            "title": str(step),
                            "status": "pending",
                        },
                    )
                )
    elif method == "event/todo_updated":
        # TodoUpdatedNotification is a V17 envelope: items live under
        # `snapshot.items` as {id, content, status} rows, not flat fields.
        snapshot = body.get("snapshot")
        items = snapshot.get("items") if isinstance(snapshot, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    (
                        "todo.updated",
                        {
                            "todo_id": str(item.get("id") or ""),
                            "title": str(item.get("content") or ""),
                            "status": str(item.get("status") or ""),
                        },
                    )
                )
    return rows


class _RunEmit:
    """Per-run emit callback: journals protocol ``event/*`` notifications and
    projects them into the reducer vocabulary on the run's own event log.

    Both surfaces are capped against floods — except ``assistant.final``,
    which is a terminal projection and always persisted: a run that floods
    the channel must never lose its answer (audit r3-F4).
    """

    def __init__(self, database_url: str, tenant_id: str, run_id: str) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.tool_names: dict[str, str] = {}
        self.journaled = 0
        self.projected = 0

    @staticmethod
    def _params(notification: Any) -> dict[str, Any]:
        """Structured fields of a protocol notification (pydantic or dict)."""
        dump = getattr(notification, "model_dump", None)
        if callable(dump):
            try:
                data = dump(mode="json")
            except Exception:
                data = None
            if isinstance(data, dict):
                return data
        if isinstance(notification, dict):
            return dict(notification)
        params = getattr(notification, "params", None)
        return dict(params) if isinstance(params, dict) else {}

    def project(self, event_type: str, body: dict[str, Any]) -> None:
        """Write one UI-facing projection row — the event types the web
        ``eventReducer`` consumes (``assistant.final``/``assistant.delta``/
        ``tool.*``/``question.*``)."""
        terminal = event_type in _TERMINAL_PROJECTIONS
        if not terminal and self.projected >= _JOURNAL_CAP:
            return
        self.projected += 1
        try:
            from rxycode_server.events.store import append_event

            append_event(
                self.database_url,
                tenant_id=self.tenant_id,
                run_id=self.run_id,
                event_type=event_type,
                payload=body,
            )
        except Exception:
            _LOG.warning(
                "run %s: projection emit failed (%s)",
                self.run_id,
                event_type,
                exc_info=True,
            )

    def __call__(self, notification: Any) -> None:
        """Journal protocol ``event/`` notifications onto the run's own event
        log — the same rows the SSE endpoint replays. Capped per run."""
        method = getattr(notification, "method", None)
        if not isinstance(method, str) or not method.startswith("event/"):
            return
        body = self._params(notification)
        if self.journaled < _JOURNAL_CAP:
            self.journaled += 1
            try:
                from rxycode_server.events.store import append_event

                append_event(
                    self.database_url,
                    tenant_id=self.tenant_id,
                    run_id=self.run_id,
                    event_type=f"notify.{method}",
                    payload={"text": str(notification)[:1500]},
                )
            except Exception:
                _LOG.warning("run %s: journal emit failed", self.run_id, exc_info=True)
        for event_type, payload in _projection_rows(
            method, body, self.tool_names, run_id=self.run_id
        ):
            self.project(event_type, payload)


async def _command_watchdog(database_url: str, run_id: str, turn: "asyncio.Task[Any]") -> None:
    """Deliver persisted steer/child-cancel commands while the turn runs —
    the drain equivalent of ``AgentWorker._watch_web_commands``."""
    from rxycode_worker.agent_events import consume_persisted_commands

    while not turn.done():
        try:
            results = await consume_persisted_commands(database_url, run_id)
            for result in results:
                if not (result.get("delivered") or result.get("accepted")):
                    _LOG.warning("run %s: command undeliverable: %s", run_id, result)
        except Exception:
            _LOG.warning("run %s: command drain failed", run_id, exc_info=True)
        await asyncio.sleep(0.3)


async def _lease_watchdog(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    *,
    lease_ttl: int,
    claimed_at: float,
    turn: "asyncio.Task[Any]",
) -> None:
    """Renew the lease while the turn runs; cancel it on ``cancel_requested``,
    ``LeaseRejected``, or when renewals cannot be proven before expiry.

    The monotonic ``deadline`` is anchored at the claim moment (``claimed_at``)
    and extended only by a *proven* renewal — a failed probe shortens nothing
    and delays nothing: the next sleep is ``min(interval, deadline - now)`` so
    the watchdog wakes at expiry even mid-outage. Every store call is bounded
    by ``wait_for`` inside the remaining budget; once the deadline passes the
    lease has expired and the turn is cancelled with ``_LeaseRenewalLost``
    instead of running unowned.
    """
    from rxycode_worker.supervisor import LeaseRejected, renew_lease

    interval = max(2.0, lease_ttl / 2.0)
    deadline = claimed_at + lease_ttl
    # Sleep wakes unprecisely — keep a margin so the renewal probe lands
    # strictly BEFORE expiry; a probe arriving at/past deadline would already
    # be unowned in DB terms.
    margin = 0.25
    while not turn.done():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _LOG.error("run %s: lease expired without a proven renewal", run_id)
            turn.cancel()
            raise _LeaseRenewalLost(run_id)
        await asyncio.sleep(min(interval, max(0.05, remaining - margin)))
        if turn.done():
            return
        now = time.monotonic()
        if now >= deadline:
            turn.cancel()
            raise _LeaseRenewalLost(run_id)
        try:
            req_start = time.monotonic()
            await asyncio.wait_for(
                asyncio.to_thread(
                    renew_lease,
                    database_url,
                    run_id,
                    worker_id,
                    epoch,
                    ttl_seconds=lease_ttl,
                ),
                timeout=max(0.05, min(_LEASE_IO_BUDGET, deadline - now)),
            )
            # Anchor at request-START, not completion: the store computes
            # lease_until from its own clock inside the transaction, so the
            # DB expiry is ~req_start+ttl — extending from completion would
            # let the turn outlive the real lease by the response latency
            # (audit r5-F1).
            deadline = req_start + lease_ttl
        except LeaseRejected:
            turn.cancel()
            raise
        except Exception as exc:
            # Covers both real store errors and wait_for timeouts. A timed-out
            # renewal keeps running in its thread — if it lands late it only
            # re-checks the fence; the conservative outcome (we step aside)
            # stays correct.
            if time.monotonic() >= deadline:
                _LOG.error(
                    "run %s: lease renewals unproven past TTL; cancelling turn",
                    run_id,
                )
                turn.cancel()
                raise _LeaseRenewalLost(run_id) from exc
            _LOG.warning(
                "run %s: lease renewal failed; retrying before lease expiry",
                run_id,
                exc_info=True,
            )
        now = time.monotonic()
        if now >= deadline:
            turn.cancel()
            raise _LeaseRenewalLost(run_id)
        try:
            status = await asyncio.wait_for(
                asyncio.to_thread(run_status, database_url, run_id),
                timeout=max(0.05, min(_LEASE_IO_BUDGET, deadline - now)),
            )
        except Exception as exc:
            status = ""
            _LOG.warning("run %s: status poll failed; retrying", run_id, exc_info=True)
            if time.monotonic() >= deadline:
                turn.cancel()
                raise _LeaseRenewalLost(run_id) from exc
        if status == "cancel_requested":
            turn.cancel()
            raise _RunCancelled(run_id)


def _execution_gate(
    target_id: str,
    permission_profile: str,
    *,
    execution_mode: str,
    tenant_id: str,
) -> str | None:
    """Resolve placement + permission for a claimed run, or refuse closed.

    The public stack contract (``cloud-only``, the compose default): only
    ``cloud:{tenant}:{workspace}`` targets execute — always inside the
    per-run userns sandbox — and the tenant segment must equal the run's
    own tenant, so a target can never bind another tenant's isolation
    context. ``local:*``/``sandbox:*`` placements and ``full``/``full_auto``
    profiles are refused: Full means unsandboxed host authority and that
    does not exist on the public worker.

    ``sandboxed-local`` is the development-host opt-in: ``local:*`` and
    tenant-bound ``cloud:*`` targets execute — still confined; the drain
    never runs a turn on the worker host.

    Returns the Session ``permission_mode`` (None = configured default).
    """
    target = str(target_id or "")
    profile = str(permission_profile or "").strip().lower()
    if execution_mode not in _EXECUTION_MODES:
        raise _UnsupportedTarget(f"unknown execution mode {execution_mode!r}; refusing the run")
    if target.startswith("cloud:"):
        parts = target.split(":", 2)
        cloud_tenant = parts[1] if len(parts) > 1 else ""
        if not cloud_tenant or cloud_tenant != str(tenant_id):
            raise _UnsupportedTarget(
                f"target {target!r} binds tenant {cloud_tenant!r} but the run "
                f"belongs to {tenant_id!r} — cross-tenant sandbox refused"
            )
    elif execution_mode == "cloud-only":
        raise _UnsupportedTarget(
            f"target {target!r} refused: the public worker executes only "
            "cloud:{tenant}:{workspace} targets inside the per-run sandbox; "
            "local/sandbox placements never reach this host"
        )
    elif not target.startswith("local:"):
        raise _UnsupportedTarget(
            f"target {target!r} is not local:*/cloud:*; refusing to execute "
            "without a declared placement"
        )
    if execution_mode == "cloud-only" and profile in {"full", "full_auto"}:
        raise _UnsupportedTarget(
            f"profile {profile!r} requests unsandboxed host authority; refused on the public stack"
        )
    return _PERMISSION_MODE_MAP.get(profile)


def _child_env(turn_env: Mapping[str, str]) -> dict[str, str]:
    """The confined process's whole environment: the passlist plus the
    per-turn RXYCODE_TURN_* contract. ``--clearenv`` drops everything else."""
    env = {key: os.environ[key] for key in _CHILD_ENV_PASS if key in os.environ}
    env.update({str(k): str(v) for k, v in turn_env.items()})
    return env


def _prepare_child_data_dir(conf_dir: Path) -> Path:
    """Per-run config home under the drain-controlled state root — a copy of
    the worker's config.yaml so model resolution reads a real file. It is
    ro-bound into the sandbox; the confined turn can never write it (and can
    never leave a destination symlink for the parent to follow).
    """
    conf_dir.mkdir(parents=True, exist_ok=True)
    source_root = os.environ.get("RXYCODE_DATA_DIR", "").strip()
    if source_root:
        source = Path(source_root) / "config.yaml"
        if source.is_file():
            try:
                shutil.copy2(source, conf_dir / "config.yaml")
            except OSError:
                _LOG.warning("copying config into the run sandbox failed", exc_info=True)
    return conf_dir


_USAGE_LINE = "__RXY_USAGE__"


async def _wait_child(
    proc: "asyncio.subprocess.Process",
    stderr_tail: list[bytes],
    usage_sink: dict[str, int] | None = None,
) -> None:
    """Wait for the confined turn; on cancellation SIGKILL the bwrap
    supervisor — --die-with-parent then reaps the whole namespace tree.

    ``__RXY_USAGE__`` lines the child writes to stderr are parsed into
    ``usage_sink`` (cumulative per attempt) as they arrive — a SIGKILL can
    never erase spend the parent already received (audit r5-F4)."""

    async def _collect() -> None:
        if proc.stderr is None:
            return
        pending = b""
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                return
            stderr_tail.append(chunk)
            del stderr_tail[:-16]  # bounded tail for the failure detail
            if usage_sink is None:
                continue
            pending = (pending + chunk)[-65536:]
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if not line.startswith(_USAGE_LINE.encode()):
                    continue
                try:
                    row = json.loads(line[len(_USAGE_LINE) :].decode("utf-8"))
                    inp = int(row.get("input_tokens") or 0)
                    outp = int(row.get("output_tokens") or 0)
                    if inp + outp > usage_sink.get("tokens", 0):
                        usage_sink["tokens"] = inp + outp
                        usage_sink["input_tokens"] = inp
                        usage_sink["output_tokens"] = outp
                except Exception:
                    continue

    collector = asyncio.ensure_future(_collect())
    try:
        await proc.wait()
    except asyncio.CancelledError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception:
            pass
        raise
    finally:
        # The pipe closes at process death — let the collector finish
        # draining buffered usage lines instead of cancelling them away
        # (a fast-exiting child can report spend in its final write).
        try:
            await asyncio.wait_for(collector, timeout=5)
        except BaseException:
            collector.cancel()
            try:
                await collector
            except BaseException:
                pass


async def run_sandboxed_turn() -> int:
    """The confined half of a drained run — entered when this module is
    executed with ``RXYCODE_TURN_RUN_ID`` set (inside the userns sandbox).

    Everything the old direct path did happens here: remember_web_run +
    publish_database_url, the _DrainWorkerShim steer channel, a REAL
    ProtocolTui bound through bind_prompt_context (the production producer
    of tool/stream notifications — audit r3-F3), the command watchdog, and
    one Session.prompt turn through AgentRuntime. The result lands in
    ``.turn-result.json`` for the drain parent; the process always exits 0
    — errors live in the result file and the journaled events.
    """
    run_id = os.environ["RXYCODE_TURN_RUN_ID"].strip()
    database_url = os.environ["RXYCODE_WEB_DATABASE_URL"].strip()
    tenant_id = os.environ.get("RXYCODE_TURN_TENANT", "")
    project_id = os.environ.get("RXYCODE_TURN_PROJECT", "")
    actor_id = os.environ.get("RXYCODE_TURN_ACTOR", "")
    session_id = os.environ.get("RXYCODE_TURN_SESSION", "") or run_id
    target_id = os.environ.get("RXYCODE_TURN_TARGET", "")
    traceparent = os.environ.get("RXYCODE_TURN_TRACEPARENT", "")
    permission_profile = os.environ.get("RXYCODE_TURN_PROFILE", "")
    permission_mode = os.environ.get("RXYCODE_TURN_PERMISSION", "").strip() or None
    model = os.environ.get("RXYCODE_WORKER_MODEL", "").strip()
    workdir = Path(os.environ.get("RXYCODE_TURN_WORKDIR", ".")).resolve()
    result_path = workdir / _TURN_RESULT

    # Config lives in a parent-owned ro-bound dir; the writable data dir is
    # inside this workspace. The child copies config.yaml itself — the
    # parent NEVER writes into the workspace (a confined turn could plant a
    # destination symlink and make a later parent copy follow it onto host
    # files — audit r4-F2).
    config_src = os.environ.get("RXYCODE_TURN_CONFIG_SRC", "").strip()
    if config_src:
        try:
            src_cfg = Path(config_src) / "config.yaml"
            dst_dir = Path(os.environ.get("RXYCODE_DATA_DIR", str(workdir / ".data")))
            dst_dir.mkdir(parents=True, exist_ok=True)
            if src_cfg.is_file():
                shutil.copy2(src_cfg, dst_dir / "config.yaml")
        except OSError:
            _LOG.warning("run %s: config copy into workspace failed", run_id, exc_info=True)

    from rxycode_server.runs.service import load_run
    from rxycode_worker.agent_events import (
        bind_run,
        clear_web_run,
        publish_database_url,
        remember_web_run,
    )

    emit = _RunEmit(database_url, tenant_id, run_id)
    publish_database_url(database_url)
    remember_web_run(
        database_url,
        tenant_id,
        run_id,
        parent_id=session_id,
        session_id=session_id,
    )

    turn_error = ""
    cancelled_by_request = False
    measured = {"tokens": 0}
    message = ""

    try:
        loaded = await asyncio.to_thread(load_run, database_url, run_id)
        message = loaded["message"]
        workdir.mkdir(parents=True, exist_ok=True)

        # The production producer of tool/stream notifications (audit r3-F3):
        # a real ProtocolTui bound via bind_prompt_context so every TUI import
        # path resolves to it through install_tui_context_hook.
        from appserver.runtime import (
            bind_prompt_context,
            install_tui_context_hook,
            reset_prompt_context,
        )
        from appserver.agent_worker import bind_worker_todo_sink
        from appserver.tui import ProtocolTui
        from rxycode_protocol.run_context import RunContext

        install_tui_context_hook()

        tui = ProtocolTui(session_id, emit, run_id=run_id)
        deadline_at = datetime.now(timezone.utc).isoformat()
        trace_id = ""
        if traceparent.count("-") >= 2:
            trace_id = traceparent.split("-")[2]
        run_context = RunContext(
            tenant_id=str(tenant_id),
            actor_id=str(actor_id or "drain"),
            project_id=str(project_id or session_id),
            session_id=session_id,
            run_id=run_id,
            target_id=str(target_id or session_id),
            permission_profile=str(permission_profile or "default"),
            deadline_at=deadline_at,
            trace_id=trace_id or uuid.uuid4().hex,
        )
        context_tokens = bind_prompt_context(session_id, tui, run_context=run_context)
        bind_worker_todo_sink(emit)

        # Imports stay inside the executed run: module import of this file
        # must not drag the whole agent stack into a bare --help process.
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        from RxyCode.RxyCode1_1_0.core.session import Session
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )
        from RxyCode.RxyCode1_1_0.main import dispatch_surface_prompt
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats
        from appserver.agent_runtime import AgentConfig, AgentRuntime
        from appserver.agent_task import LifecycleState
        from appserver.eventbus import AppendOnlyLog, EventBus

        token0 = (
            int(token_stats.input_tokens),
            int(token_stats.output_tokens),
        )
        attempt_epoch = os.environ.get("RXYCODE_TURN_EPOCH", "")

        # Zero-window metering (audit r5): wrap the single real-usage choke
        # point so EVERY recorded provider response immediately emits a
        # cumulative `__RXY_USAGE__` line on stderr — the parent's pipe
        # reader holds it before a SIGKILL can land, so a killed turn keeps
        # its spend up to the last completed response.
        _orig_add_real_usage = token_stats.add_real_usage

        def _metered(*args: Any, **kwargs: Any) -> Any:
            out = _orig_add_real_usage(*args, **kwargs)
            try:
                inp = int(token_stats.input_tokens) - token0[0]
                outp = int(token_stats.output_tokens) - token0[1]
                sys.stderr.write(
                    "__RXY_USAGE__"
                    + json.dumps(
                        {"input_tokens": inp, "output_tokens": outp, "attempt": attempt_epoch}
                    )
                    + "\n"
                )
                sys.stderr.flush()
            except Exception:
                pass
            return out

        token_stats.add_real_usage = _metered  # type: ignore[assignment]

        async def _usage_heartbeat() -> None:
            """Durable metering that also survives a PARENT crash: snapshot the
            real token_stats delta every few seconds onto the run's own event
            log, tagged with this attempt's lease epoch so retries accumulate
            instead of overwriting (audit r5-F4)."""
            while True:
                await asyncio.sleep(3.0)
                try:
                    inp = int(token_stats.input_tokens) - token0[0]
                    outp = int(token_stats.output_tokens) - token0[1]
                    if inp + outp <= 0:
                        continue
                    from rxycode_server.events.store import append_event

                    await asyncio.to_thread(
                        append_event,
                        database_url,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        event_type="usage.delta",
                        payload={
                            "input_tokens": inp,
                            "output_tokens": outp,
                            "cumulative": True,
                            "attempt": attempt_epoch,
                        },
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOG.warning("run %s: usage heartbeat failed", run_id, exc_info=True)

        usage_heartbeat = asyncio.ensure_future(_usage_heartbeat())

        session = Session(
            session_id=session_id,
            workspace_root=workdir,
            emit=emit,
        )
        agent = AgentV2(model_name=model or None, session_id=session_id)

        runtime = AgentRuntime(
            EventBus(AppendOnlyLog()),
            run_factory=lambda _cfg: _target,
        )
        agent_id = f"web-run-{run_id[:12]}"

        async def _target(_task_str: str, checkpoint: object | None = None) -> str:
            try:
                result = await dispatch_surface_prompt(
                    "web",
                    session,
                    agent,
                    message,
                    mode="build",
                    run_id=run_id,
                    permission_mode=permission_mode,
                    run_context=run_context,
                    tui=tui,
                )
            finally:
                delta = max(
                    0,
                    int(token_stats.input_tokens)
                    + int(token_stats.output_tokens)
                    - token0[0]
                    - token0[1],
                )
                measured["tokens"] = delta
                try:
                    runtime.record_token_usage(agent_id, delta, run_id=run_id)
                except Exception:
                    _LOG.warning("run %s: token snapshot failed", run_id, exc_info=True)
            if getattr(result, "status", "") != "succeeded":
                raise RuntimeError(
                    getattr(result, "detail", "") or f"prompt status {result.status}"
                )
            return str(getattr(result, "answer", "") or "")

        # Persisted steer channel: accept_steer finds this worker by run_id,
        # appends to _steer_queue, and Session.prompt drains it mid-turn. The
        # hook is bound BEFORE spawn — prompt() reads drain_steers when the
        # turn first runs, so wiring it after spawn would race.
        shim = _DrainWorkerShim(run_id, session_id)
        session.drain_steers = shim._take_steers
        bind_run(run_id, worker=shim, tree_root=session_id)

        agent_task = await runtime.spawn(AgentConfig(agent_id=agent_id, model=model or "active"))
        main_task = agent_task._main_task
        assert main_task is not None
        shim._turn = main_task

        command_watcher = asyncio.create_task(_command_watchdog(database_url, run_id, main_task))
        # Session.prompt binds the session's own ContextVar; tool work that
        # escaped it (threads started off the loop) resolves "latest" — point
        # that alias at the run workspace too so strays land inside it.
        latest_token = bind_session("latest")
        try:
            set_working_directory(workdir)
        finally:
            reset_session_binding(latest_token)
        try:
            await asyncio.shield(main_task)
        except asyncio.CancelledError:
            cancelled_by_request = True
        finally:
            command_watcher.cancel()
            usage_heartbeat.cancel()
            try:
                await command_watcher
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            try:
                await usage_heartbeat
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            reset_prompt_context(context_tokens)
        if not turn_error and agent_task.state != LifecycleState.DONE:
            last = getattr(agent_task, "_last_error", None)
            if last is not None:
                turn_error = f"{type(last).__name__}: {last}"
            elif not cancelled_by_request:
                turn_error = f"agent ended in state {agent_task.state}"
    except asyncio.CancelledError:
        cancelled_by_request = True
    except Exception as exc:
        turn_error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            clear_web_run()
        except Exception:
            pass
        try:
            from rxycode_worker.agent_events import _BOUND

            _BOUND.pop(run_id, None)
        except Exception:
            pass
        # The result file is the parent's contract: status + real measured
        # tokens + the honest error string, written best-effort — a missing
        # file means the sandbox was killed and the parent reports that.
        try:
            result_path.write_text(
                json.dumps(
                    {
                        # run_id binds the file to THIS run — a stale file from
                        # an earlier run in a reused workspace can never be
                        # accepted as the outcome (audit r4-F3).
                        "run_id": run_id,
                        "status": (
                            "cancelled"
                            if cancelled_by_request
                            else "succeeded"
                            if not turn_error
                            else "failed"
                        ),
                        "error": turn_error[:1500],
                        "tokens": int(measured["tokens"]),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            _LOG.warning("run %s: turn result file write failed", run_id, exc_info=True)
    return 0


def _read_turn_result(workdir: Path) -> dict[str, Any]:
    """The confined turn's report. Missing/corrupt => the caller decides —
    a killed sandbox leaves no file and the drain reports its own cause."""
    path = workdir / _TURN_RESULT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _has_prior_attempt_activity(
    database_url: str, run_id: str, epoch: int
) -> bool:
    """True when any event predates this worker's claim — a prior attempt's
    lease, metering, or agent lifecycle rows mean 'cancel_requested before
    WE ran' does NOT mean nothing ran (audit r13)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT COUNT(*) FROM run_events WHERE run_id = :id AND ("
                    "  type IN ('usage.delta', 'event/agent_done', 'event/agent_started')"
                    "  OR (type = 'worker.lease' AND "
                    "      CAST(payload->>'epoch' AS INTEGER) <> :ep)"
                    ")"
                ),
                {"id": run_id, "ep": int(epoch)},
            ).scalar()
        return int(n or 0) > 0
    finally:
        engine.dispose()


def _reconcile_lost_lease_ledger(
    database_url: str,
    tenant_id: str,
    run_id: str,
    attempt_key: str,
    streamed: dict[str, int],
    deltas: dict[str, int],
) -> bool:
    """After a lost lease, a successful flush only journaled a delta — a
    retry that finalized before it landed keeps a short ledger unless we
    reconcile here (audit r13/r14). Recompute the full per-attempt total
    from a FRESH read of the durable deltas (our in-memory copy predates
    the other owner's commits — audit r14), raise the committed ledger
    when one exists. Returns False when no ledger exists YET — the caller
    must retain a pending reconcile (journaled spool) instead of trusting
    the new owner to have aggregated our late delta in time. Exceptions
    propagate — they mean "unknown", not "safe"."""
    from rxycode_server.usage.service import adjust_terminal_usage

    fresh = _usage_deltas_by_attempt(database_url, run_id)
    merged = {
        a: max(fresh.get(a, 0), deltas.get(a, 0))
        for a in set(fresh) | set(deltas)
    }
    dones, attributions = _agent_done_by_attempt(database_url, run_id)
    per_attempt = {
        a: max(merged.get(a, 0), dones.get(a, 0))
        for a in set(merged) | set(dones)
    }
    per_attempt[attempt_key] = max(
        per_attempt.get(attempt_key, 0), int(streamed.get("tokens") or 0)
    )
    total = sum(per_attempt.values())
    if total <= 0:
        return True
    return (
        adjust_terminal_usage(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            tokens=total,
            event_id=uuid.uuid4().hex,
            attribution=attributions,
            recompute=lambda: _run_metering_total(database_url, run_id),
        )
        is not None
    )




async def execute_run(
    cfg: WorkerConfig,
    run_id: str,
) -> bool:
    """Claim and execute one run: the turn itself runs inside the per-run
    sandbox; this process only claims, watches and commits.

    Returns True when this worker owned the run end to end. A lost claim or a
    lost lease returns False — the row is never half-written by two owners.
    """
    from rxycode_worker.supervisor import (
        LeaseRejected,
        claim,
        commit_terminal,
        confirm_cancel,
    )

    # Anchor BEFORE the claim call: the store writes lease_until from its own
    # clock inside the claim transaction, so post-commit latency would let
    # our deadline trail the real expiry (audit r6).
    claimed_at = time.monotonic()
    epoch = await asyncio.to_thread(
        claim, cfg.database_url, run_id, cfg.worker_id, ttl_seconds=cfg.lease_ttl
    )
    if epoch is None:
        return False

    from rxycode_server.events.store import append_event
    from rxycode_server.runs.service import load_run
    from rxycode_server.usage.service import upsert_terminal_usage

    identity = await asyncio.to_thread(_run_identity, cfg.database_url, run_id)
    tenant_id = identity["tenant_id"]

    # A run cancel_requested at claim time never executes ON THIS worker —
    # but a prior attempt may have run and died: its spend and in-flight
    # effects are still real (audit r13). Only a genuinely fresh run
    # confirms cleanly; otherwise recover prior spend onto the ledger and
    # let confirm_cancel mark it recovery_required.
    if await asyncio.to_thread(run_status, cfg.database_url, run_id) == "cancel_requested":
        prior = await asyncio.to_thread(
            _has_prior_attempt_activity, cfg.database_url, run_id, epoch
        )
        if prior:
            deltas0 = await asyncio.to_thread(
                _usage_deltas_by_attempt, cfg.database_url, run_id
            )
            dones0, attributions0 = await asyncio.to_thread(
                _agent_done_by_attempt, cfg.database_url, run_id
            )
            total0 = sum(
                max(deltas0.get(a, 0), dones0.get(a, 0))
                for a in set(deltas0) | set(dones0)
            )
            if total0 > 0:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            upsert_terminal_usage,
                            cfg.database_url,
                            tenant_id=tenant_id,
                            run_id=run_id,
                            model_id=_ledger_model(cfg.model),
                            price_version=_PRICE_VERSION,
                            tokens=total0,
                            event_id=uuid.uuid4().hex,
                            attribution=attributions0,
                            recompute=lambda: _run_metering_total(
                                cfg.database_url, run_id
                            ),
                        ),
                        timeout=_LEASE_IO_BUDGET,
                    )
                except Exception:
                    _LOG.warning(
                        "run %s: cancelled-run ledger write failed",
                        run_id,
                        exc_info=True,
                    )
                    # Terminalizing with the prior spend unledgured leaves
                    # nothing pending — park a journaled spool so replay
                    # inserts or reconciles the ledger (audit r14/r15). The
                    # prior attempt's deltas are durable reads, so
                    # journaled=True is honest here.
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                _ensure_pending_reconcile_spool,
                                cfg.workspaces_root,
                                tenant_id=tenant_id,
                                run_id=run_id,
                                epoch=epoch,
                                input_tokens=0,
                                output_tokens=0,
                                journaled=True,
                                model_id=_ledger_model(cfg.model),
                                price_version=_PRICE_VERSION,
                            ),
                            timeout=_LEASE_IO_BUDGET,
                        )
                    except Exception:
                        _LOG.warning(
                            "run %s: pending-reconcile spool failed",
                            run_id,
                            exc_info=True,
                        )
            if attributions0:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            _emit_attribution_events,
                            cfg.database_url,
                            tenant_id,
                            run_id,
                            attributions0,
                        ),
                        timeout=_LEASE_IO_BUDGET,
                    )
                except Exception:
                    _LOG.warning(
                        "run %s: attribution notes failed", run_id, exc_info=True
                    )
        confirm_cancel(
            cfg.database_url,
            run_id,
            cfg.worker_id,
            epoch,
            effects_known=not prior,
        )
        return True

    ledger_model = _ledger_model(cfg.model)
    turn_error = ""
    cancelled_by_request = False
    lost_lease = False
    tokens = 0
    sandbox_id = ""
    provider = None
    workdir: Path | None = None
    proc: "asyncio.subprocess.Process | None" = None
    stderr_tail: list[bytes] = []
    streamed: dict[str, int] = {"tokens": 0}

    # Mark execution start on the durable log so a consumer can distinguish
    # "queued forever" from "a worker took it and is running the turn".
    try:
        await asyncio.to_thread(
            append_event,
            cfg.database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="worker.lease",
            payload={"worker_id": cfg.worker_id, "epoch": int(epoch)},
        )
    except Exception:
        _LOG.warning("run %s: worker.lease event failed", run_id, exc_info=True)

    turn_task: asyncio.Task[Any] | None = None
    try:
        # Everything that can fail BEFORE the turn starts lives inside the
        # failure path: a corrupt run row, a refused placement, or a host
        # without userns must end in `commit_terminal("failed")`, not an
        # orphaned lease that retries forever.
        loaded = await asyncio.to_thread(load_run, cfg.database_url, run_id)
        session_id = loaded["session_id"] or run_id
        target_id = str(loaded.get("target_id") or "")
        permission_profile = str(loaded.get("permission_profile") or "")
        permission_mode = _execution_gate(
            target_id,
            permission_profile,
            execution_mode=cfg.execution_mode,
            tenant_id=tenant_id,
        )

        from rxycode_runner.sandbox.userns import (
            UsernsSandboxProvider,
            userns_available,
        )

        if not userns_available():
            raise _UnsupportedTarget(
                "userns/bwrap isolation is unavailable on this host; "
                "the run is refused instead of executing unconfined"
            )
        provider = UsernsSandboxProvider(Path(cfg.workspaces_root))
        handle = provider.create(tenant_id=tenant_id, workspace_id=session_id, retain=False)
        sandbox_id = handle.sandbox_id
        # Per-tenant workspace: the sandbox's only writable path.
        workdir = provider.workspaces_root / tenant_id / session_id
        workdir.mkdir(parents=True, exist_ok=True)
        # The config home lives OUTSIDE the writable workspace (a confined
        # turn could otherwise plant a symlinked config.yaml for the
        # unsandboxed parent to overwrite on the next run — audit r4).
        data_dir = _prepare_child_data_dir(provider.state_root / f"{sandbox_id}-conf")
        # A stale result file from an earlier run in this workspace must
        # never be read as this run's outcome (audit r4-F3). The copied
        # config is dropped too — a removed provider must not survive into
        # the next run of a reused workspace.
        (workdir / _TURN_RESULT).unlink(missing_ok=True)
        ws_data = workdir / ".data"
        # .data is child-controlled: never follow a planted symlink — the
        # unlink only runs when .data is a real directory (or absent).
        if ws_data.is_dir() and not ws_data.is_symlink():
            (ws_data / "config.yaml").unlink(missing_ok=True)

        child_env = _child_env(
            {
                "RXYCODE_TURN_RUN_ID": run_id,
                "RXYCODE_TURN_TENANT": tenant_id,
                "RXYCODE_TURN_PROJECT": identity["project_id"],
                "RXYCODE_TURN_ACTOR": identity["actor_id"],
                "RXYCODE_TURN_SESSION": session_id,
                "RXYCODE_TURN_TARGET": target_id,
                "RXYCODE_TURN_PROFILE": permission_profile,
                "RXYCODE_TURN_PERMISSION": permission_mode or "",
                "RXYCODE_TURN_TRACEPARENT": identity["traceparent"],
                "RXYCODE_TURN_WORKDIR": str(workdir),
                "RXYCODE_TURN_EPOCH": str(epoch),
                # Two distinct dirs: the config source is a parent-owned
                # path that is only ro-bound into the sandbox (the child
                # reads config.yaml FROM it), while RXYCODE_DATA_DIR points
                # INSIDE the writable workspace so caches/sessions write
                # freely. The parent never writes into the workspace — the
                # confined child copies the config itself (audit r4-F2).
                "RXYCODE_TURN_CONFIG_SRC": str(data_dir),
                "RXYCODE_DATA_DIR": str(workdir / ".data"),
            }
        )
        # The same module re-entered in turn mode — the sandbox sees the
        # system paths plus every code path this host actually uses
        # (container /repo, dev-host PYTHONPATH entries) read-only, and the
        # parent-controlled config dir read-only as RXYCODE_DATA_DIR.
        ro_binds = ["/repo", str(data_dir)] + [
            entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry
        ]
        argv = provider.spawn_argv(
            sandbox_id,
            tenant_id=tenant_id,
            argv=[sys.executable, "-m", "rxycode_worker.drain"],
            env=child_env,
            ro_binds=ro_binds,
        )
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        record = provider._load(sandbox_id, tenant_id)
        record["pid"] = proc.pid
        record["status"] = "running"
        provider._write(sandbox_id, record)

        turn_task = asyncio.ensure_future(_wait_child(proc, stderr_tail, streamed))
        lease_watcher = asyncio.create_task(
            _lease_watchdog(
                cfg.database_url,
                run_id,
                cfg.worker_id,
                epoch,
                lease_ttl=cfg.lease_ttl,
                claimed_at=claimed_at,
                turn=turn_task,
            )
        )
        try:
            await asyncio.wait_for(asyncio.shield(turn_task), timeout=cfg.run_timeout)
        except asyncio.TimeoutError:
            turn_error = f"run timed out after {cfg.run_timeout}s"
            turn_task.cancel()
            try:
                await turn_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
        finally:
            lease_watcher.cancel()
            try:
                await lease_watcher
            except _RunCancelled:
                cancelled_by_request = True
            except (LeaseRejected, _LeaseRenewalLost):
                lost_lease = True
            except asyncio.CancelledError:
                pass
            try:
                await turn_task
            except asyncio.CancelledError:
                pass

        if not turn_error and not cancelled_by_request and not lost_lease:
            result = _read_turn_result(workdir)
            tokens = int(result.get("tokens") or 0)
            status = str(result.get("status") or "")
            # The result file must name THIS run and the child's exit code
            # must agree — a leftover file or a crashed-after-report child
            # can never be read as success (audit r4-F3).
            if str(result.get("run_id") or "") != run_id:
                status = ""
                tokens = 0
            if status == "succeeded":
                if proc.returncode != 0:
                    turn_error = (
                        f"sandboxed turn reported succeeded but exited rc={proc.returncode}"
                    )
            elif status == "cancelled":
                cancelled_by_request = True
            else:
                detail = str(result.get("error") or "")
                if proc.returncode not in (0, None):
                    detail = detail or f"sandboxed turn exited rc={proc.returncode}"
                if not detail:
                    detail = (
                        "sandboxed turn reported failure without detail"
                        if status == "failed"
                        else f"sandboxed turn produced no result (rc={proc.returncode})"
                    )
                tail = b"".join(stderr_tail)[-600:].decode("utf-8", "replace")
                if tail.strip():
                    detail = f"{detail} [stderr tail: {tail.strip()[-300:]}]"
                turn_error = detail
    except LeaseRejected:
        lost_lease = True
    except Exception as exc:
        turn_error = f"{type(exc).__name__}: {exc}"
    finally:
        # A leftover confined child must not outlive the drain's decision.
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        if provider is not None and sandbox_id:
            try:
                provider.destroy(sandbox_id, tenant_id=tenant_id)
            except Exception:
                pass

    # Non-terminal metering flush — runs on EVERY exit path including lost
    # lease: spend the pipe already delivered becomes one durable
    # usage.delta row for this attempt so a retry's ledger can recover it
    # (audit r7). Journaling, not terminal state — ownership is untouched.
    attempt_key = str(epoch)
    try:
        deltas = await asyncio.wait_for(
            asyncio.to_thread(_usage_deltas_by_attempt, cfg.database_url, run_id),
            timeout=_LEASE_IO_BUDGET,
        )
    except Exception:
        deltas = {}
    if int(streamed.get("tokens") or 0) > deltas.get(attempt_key, 0):
        # Transient DB failures get a bounded retry; a persistent outage
        # spools the metering to parent-owned disk for a later drain pass
        # instead of silently discarding known spend (audit r8).
        flushed = False
        for _attempt_no in range(3):
            try:
                # Bounded: a stuck row lock must not pin the drain past the
                # lease — the spool fallback keeps the spend (audit r9).
                flushed = await asyncio.wait_for(
                    asyncio.to_thread(
                        _flush_streamed_usage,
                        cfg.database_url,
                        tenant_id,
                        run_id,
                        epoch,
                        streamed,
                        deltas,
                    ),
                    timeout=_LEASE_IO_BUDGET,
                )
            except Exception:
                flushed = False
            if flushed:
                break
            await asyncio.sleep(0.5)
        if flushed:
            deltas[attempt_key] = int(streamed["tokens"])
        else:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _spool_streamed_usage,
                        _usage_spool_dir(cfg.workspaces_root),
                        tenant_id=tenant_id,
                        run_id=run_id,
                        epoch=epoch,
                        input_tokens=int(streamed.get("input_tokens") or 0),
                        output_tokens=int(streamed.get("output_tokens") or 0),
                        model_id=ledger_model,
                        price_version=_PRICE_VERSION,
                    ),
                    timeout=_LEASE_IO_BUDGET,
                )
            except Exception:
                _LOG.warning(
                    "run %s: usage spool write failed; spend may be lost",
                    run_id,
                    exc_info=True,
                )
    # True when streamed spend is still NOT journaled — flush failed and the
    # deltas snapshot never absorbed it. A pending-reconcile spool written
    # now must carry journaled=False or replay could delete the file having
    # never appended this attempt's spend (audit r15).
    metering_owed = int(streamed.get("tokens") or 0) > deltas.get(
        attempt_key, 0
    )

    if lost_lease:
        # Our flushed usage.delta is durable but a retry may already have
        # committed a short ledger — reconcile before handing off (r13).
        # No ledger YET (or a failed reconcile) is NOT safe to drop: the
        # other owner may commit its own short total next — park a journaled
        # pending-reconcile spool so a later drain pass converges (r14).
        pending = False
        try:
            landed = await asyncio.wait_for(
                asyncio.to_thread(
                    _reconcile_lost_lease_ledger,
                    cfg.database_url,
                    tenant_id,
                    run_id,
                    attempt_key,
                    streamed,
                    deltas,
                ),
                timeout=_LEASE_IO_BUDGET,
            )
            pending = not landed
        except Exception:
            pending = True
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _ensure_pending_reconcile_spool,
                        cfg.workspaces_root,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        epoch=epoch,
                        input_tokens=int(streamed.get("input_tokens") or 0),
                        output_tokens=int(streamed.get("output_tokens") or 0),
                        journaled=not metering_owed,
                        model_id=ledger_model,
                        price_version=_PRICE_VERSION,
                    ),
                    timeout=_LEASE_IO_BUDGET,
                )
            except Exception:
                _LOG.warning(
                    "run %s: pending-reconcile spool write failed",
                    run_id,
                    exc_info=True,
                )
            _LOG.warning(
                "run %s: lease lost mid-flight; reconcile parked on spool",
                run_id,
            )
        else:
            _LOG.warning(
                "run %s: lease lost mid-flight; new owner finishes", run_id
            )
        return False

    # Real spend lands on the ledger for succeeded, failed AND cancelled runs
    # alike — the metered delta is the truth even when agent_done never
    # journaled (it only writes on success).
    agent_done_id = uuid.uuid4().hex
    try:
        agent_done_id_found, done_tokens = await asyncio.wait_for(
            asyncio.to_thread(_agent_done_row, cfg.database_url, run_id),
            timeout=_LEASE_IO_BUDGET,
        )
        if agent_done_id_found:
            agent_done_id = agent_done_id_found
    except Exception:
        pass
    # Metering model: every source is a CUMULATIVE snapshot of ITS OWN
    # attempt's spend — merge within an attempt by max, sum across epochs
    # (disjoint spends). agent_done rows are epoch-tagged by RunJournal, so
    # a prior attempt's meter lands in ITS bucket, never double-counted.
    try:
        dones, attributions = await asyncio.wait_for(
            asyncio.to_thread(_agent_done_by_attempt, cfg.database_url, run_id),
            timeout=_LEASE_IO_BUDGET,
        )
    except Exception:
        dones, attributions = {}, []
    per_attempt: dict[str, int] = {
        a: max(deltas.get(a, 0), dones.get(a, 0)) for a in set(deltas) | set(dones)
    }
    per_attempt[attempt_key] = max(
        per_attempt.get(attempt_key, 0),
        tokens,  # the result file (current attempt only)
        int(streamed.get("tokens") or 0),
    )
    tokens = sum(per_attempt.values())
    usage_error = ""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                upsert_terminal_usage,
                cfg.database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                model_id=ledger_model,
                price_version=_PRICE_VERSION,
                tokens=tokens,
                event_id=agent_done_id,
                attribution=attributions,
                recompute=lambda: _run_metering_total(
                    cfg.database_url, run_id
                ),
            ),
            timeout=_LEASE_IO_BUDGET,
        )
    except Exception as exc:
        usage_error = f"terminal usage write failed: {type(exc).__name__}: {exc}"
        _LOG.warning("run %s: %s", run_id, usage_error, exc_info=True)
    # `upsert_terminal_usage` writes the RUN-LEVEL aggregate: an existing
    # shorter ledger (a prior attempt committed partial spend and crashed
    # before its terminal write — audit r12) is reconciled up to the
    # recomputed total inside the same run lock; a fresh ledger inserts.
    if attributions:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    _emit_attribution_events,
                    cfg.database_url,
                    tenant_id,
                    run_id,
                    attributions,
                ),
                timeout=_LEASE_IO_BUDGET,
            )
        except Exception:
            _LOG.warning(
                "run %s: attribution notes failed", run_id, exc_info=True
            )
            # Durable uncertainty must not depend on one append: park a
            # spool so a later drain pass re-emits the deduped
            # `usage.attribution` notes (audit r14); journaled mirrors
            # whether this attempt's streamed spend is durable (r15).
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _ensure_pending_reconcile_spool,
                        cfg.workspaces_root,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        epoch=epoch,
                        input_tokens=int(streamed.get("input_tokens") or 0),
                        output_tokens=int(streamed.get("output_tokens") or 0),
                        journaled=not metering_owed,
                        model_id=ledger_model,
                        price_version=_PRICE_VERSION,
                    ),
                    timeout=_LEASE_IO_BUDGET,
                )
            except Exception:
                _LOG.warning(
                    "run %s: pending-attribution spool write failed",
                    run_id,
                    exc_info=True,
                )

    if cancelled_by_request:
        # A cancelled run is still committed cancelled — the cancel was real
        # — but a failed ledger write is surfaced on the durable log first,
        # never dropped silently.
        if usage_error:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        append_event,
                        cfg.database_url,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        event_type="run.error",
                        payload={
                            "detail": usage_error[:1500],
                            "worker_id": cfg.worker_id,
                        },
                    ),
                    timeout=_LEASE_IO_BUDGET,
                )
            except Exception:
                _LOG.warning(
                    "run %s: run.error for usage failure failed",
                    run_id,
                    exc_info=True,
                )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    confirm_cancel,
                    cfg.database_url,
                    run_id,
                    cfg.worker_id,
                    epoch,
                    effects_known=False,
                ),
                timeout=_LEASE_IO_BUDGET,
            )
        except LeaseRejected:
            return False
        return True

    # A failed durable ledger write is a durable-write failure: it must turn
    # the run's terminal state into `failed`, never let `succeeded` stand on
    # a missing usage row.
    if usage_error:
        turn_error = f"{turn_error}; {usage_error}" if turn_error else usage_error
    terminal = "succeeded" if not turn_error else "failed"
    if turn_error:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    append_event,
                    cfg.database_url,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type="run.error",
                    payload={
                        "detail": turn_error[:1500],
                        "worker_id": cfg.worker_id,
                    },
                ),
                timeout=_LEASE_IO_BUDGET,
            )
        except Exception:
            _LOG.warning("run %s: run.error event failed", run_id, exc_info=True)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                commit_terminal,
                cfg.database_url,
                run_id,
                cfg.worker_id,
                epoch,
                terminal,
            ),
            timeout=_LEASE_IO_BUDGET,
        )
    except LeaseRejected:
        return False
    return True


async def drain_once(cfg: WorkerConfig) -> bool:
    """Claim and execute at most one run. True means a run ran."""
    # Retry any metering that survived on disk after a DB outage — a lost
    # lease can never silently discard spend the pipe already delivered.
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_replay_usage_spool, cfg.database_url, cfg.workspaces_root),
            timeout=_LEASE_IO_BUDGET * 4,
        )
    except Exception:
        _LOG.warning("usage spool replay failed", exc_info=True)
    for run_id in claimable_run_ids(cfg.database_url, limit=3):
        if await execute_run(cfg, run_id):
            return True
    return False


async def run_forever(cfg: WorkerConfig) -> None:
    """Poll the durable queue forever. Per-iteration failures never kill the
    loop — a wedged run must not take down the only consumer."""
    _LOG.info(
        "worker drain started: worker_id=%s mode=%s poll=%.1fs lease_ttl=%ds timeout=%.0fs",
        cfg.worker_id,
        cfg.execution_mode,
        cfg.poll_seconds,
        cfg.lease_ttl,
        cfg.run_timeout,
    )
    while True:
        did = False
        try:
            did = await drain_once(cfg)
        except Exception:
            _LOG.exception("drain iteration failed")
        if not did:
            await asyncio.sleep(cfg.poll_seconds)


def main() -> None:
    """``python -m rxycode_worker.drain`` / ``python -m rxycode_worker``.

    With ``RXYCODE_TURN_RUN_ID`` set this process IS the confined turn —
    spawned by the drain under the userns sandbox. Without it, this is the
    drain loop itself.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if os.environ.get("RXYCODE_TURN_RUN_ID", "").strip():
        sys.exit(asyncio.run(run_sandboxed_turn()))
    cfg = worker_config_from_env()
    asyncio.run(run_forever(cfg))


if __name__ == "__main__":
    main()
