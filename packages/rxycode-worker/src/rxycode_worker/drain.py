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
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

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

#: Loopback port the in-sandbox relay listens on — each turn's private net
#: namespace means the same port never collides between runs.
_EGRESS_PORT = 18881

#: Environment the confined turn receives. Everything else is stripped by
#: --clearenv — a run never inherits worker secrets it was not granted.
_CHILD_ENV_PASS = (
    "PATH",
    "USER",
    "LANG",
    "LC_ALL",
    "TERM",
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "RXYCODE_UVLOOP",
    "RXYCODE_WORKER_MODEL",
    "RXYCODE_LLM_MODEL",
)
# Never in the passlist, by design: RXYCODE_WEB_DATABASE_URL (the platform
# control-plane credential — a confined turn reaches it only through the
# parent-owned control socket), RXYCODE_API_KEY / RXYCODE_LLM_BASE_URL (the
# platform model credential — the child's model entry is rewritten to the
# loopback gateway and the PARENT injects real auth upstream), HOME (set
# to a task-private dir per turn), and Docker socket / other tenants'
# credentials (never mounted, never forwarded).


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

    def __init__(
        self,
        database_url: str,
        tenant_id: str,
        run_id: str,
        emitter: Any | None = None,
    ) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.tool_names: dict[str, str] = {}
        self.journaled = 0
        self.projected = 0
        # Confined turns carry no platform credentials: ``emitter`` is the
        # parent's TurnChannel.emit — the row lands on the same event log.
        self._emitter = emitter

    def _append(self, event_type: str, body: dict[str, Any]) -> None:
        if self._emitter is not None:
            self._emitter(event_type, dict(body))
            return
        from rxycode_server.events.store import append_event

        append_event(
            self.database_url,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            event_type=event_type,
            payload=body,
        )

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
            self._append(event_type, body)
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
                self._append(
                    f"notify.{method}",
                    {"text": str(notification)[:1500]},
                )
            except Exception:
                _LOG.warning("run %s: journal emit failed", self.run_id, exc_info=True)
        for event_type, payload in _projection_rows(
            method, body, self.tool_names, run_id=self.run_id
        ):
            self.project(event_type, payload)


async def _command_watchdog(fetch: Any, run_id: str, turn: "asyncio.Task[Any]") -> None:
    """Deliver persisted steer/child-cancel commands while the turn runs —
    the drain equivalent of ``AgentWorker._watch_web_commands``. ``fetch``
    is ``after_seq -> [event]``: DB reads on the trusted side, the control
    channel inside the confined turn."""
    from rxycode_worker.agent_events import consume_commands_via

    while not turn.done():
        try:
            results = await consume_commands_via(fetch, run_id)
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
    context. ``local:*``/``sandbox:*`` placements are refused on the public
    worker.

    Permission profile is an APPROVAL semantic only — never an isolation
    level. ``full``/``full_auto`` on a valid tenant-owned cloud target
    resolves to ``full_auto`` (no prompts) INSIDE the same sandbox: same
    mounts, same private network namespace, same egress filter, same
    writable domain. No profile can widen the kernel boundary; local-CLI
    Full semantics live in ``core/sandbox/policy.py`` and are untouched.

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
    # Invariants on every accepted path: execution_target is the tenant's
    # own cloud sandbox (userns is unconditionally created below — it can
    # never be skipped), isolation_required always holds, and the returned
    # mode maps `full`/`full_auto` to the existing no-approval mode.
    return _PERMISSION_MODE_MAP.get(profile)


def _child_env(turn_env: Mapping[str, str]) -> dict[str, str]:
    """The confined process's whole environment: the passlist plus the
    per-turn RXYCODE_TURN_* contract. ``--clearenv`` drops everything else."""
    env = {key: os.environ[key] for key in _CHILD_ENV_PASS if key in os.environ}
    env.update({str(k): str(v) for k, v in turn_env.items()})
    return env


def _trusted_child_argv() -> list[str]:
    """The confined worker's interpreter argv — import hardening for
    THIS entrypoint only (audit W8-r7/r8):

    - ``-P`` (>=3.11) keeps the spawn cwd off ``sys.path``;
    - ``-s`` skips the USER site — the task HOME is writable, so a
      ``.pth`` hook planted under ``.home/.local/...`` would otherwise
      execute before the trusted module and replace the approval
      machinery. System/site paths on PYTHONPATH are ro-bound, so
      user-site is the only writable startup hook.

    Neither flag is inherited by descendants (no PYTHONSAFEPATH /
    PYTHONNOUSERSITE env): a task's own ``python -c 'import
    solution'`` must resolve the workspace normally — ordinary
    sandbox code needs no bootstrap hardening."""
    return [
        sys.executable,
        *(["-P"] if sys.version_info >= (3, 11) else []),
        "-s",
        "-m",
        "rxycode_worker.drain",
    ]


# Credential-shaped config keys die at the sandbox boundary — matched
# anywhere in the copied config, not only under ``models`` (audit W8-r2:
# ``rag.embedding.api_key`` and MCP-server env vars like GITHUB_TOKEN are
# supported config fields that would otherwise be mounted verbatim).
# Suffixes are exact-on-word-boundary: ``max_tokens``/``token_budget``/
# ``sort_key`` are config, not secrets, and must survive.
_CREDENTIAL_KEYS_EXACT = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "token",
        "auth_token",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "secret",
        "password",
        "passwd",
        "pwd",
        "private_key",
        "credentials",
        "bearer_token",
        "session_token",
        "signing_key",
        "webhook_secret",
        "encryption_key",
    }
)
_CREDENTIAL_KEY_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_api_secret",
    "_token",
    "_secret",
    "_password",
    "_passwd",
    "_private_key",
    "_access_key",
    "_client_secret",
    "_auth_token",
    "_credentials",
    "_bearer_token",
    "_signing_key",
    "_webhook_secret",
)
# Indirection keys hold a RESOLVER (env var name / file path), not the
# secret itself — blank them so the child-side resolver finds nothing.
_CREDENTIAL_INDIRECTION_KEYS = frozenset(
    {
        "api_key_env",
        "api_key_secret",
        "api_key_file",
        "token_env",
        "token_file",
        "secret_env",
        "secret_file",
        "password_env",
        "password_file",
        "credentials_file",
        "credential_file",
        "private_key_file",
        "auth_file",
        "passfile",
    }
)
# Run-together credential names the exact/suffix tables miss —
# ``PGPASSWORD``, ``ACCESSTOKEN``, ``DATABASE_DSN``, ``AWSSECRET`` are
# supported env/config spellings (audit W8-r3). Still suffix-anchored:
# ``max_tokens``/``sort_key``/``token_budget`` survive.
_CREDENTIAL_BARE_RE = re.compile(
    r"(?:password|passwd|pwd|secret|token|credentials?|dsn|privatekey)$"
)
# A URL with an embedded userinfo password is a credential wherever it
# sits — ``database_url``/``dsn`` keys are not credential-NAMED but a
# ``scheme://user:pass@host`` value still hands the child a live login.
# No length ceiling — a 300-char password is still a password
# (audit W8-r15). The password charset excludes ``/``/``?``/``#`` —
# RFC 3986 ends the authority at each, and their exclusion keeps
# port+path ``:443/@scope`` and query/fragment ``:443?x=@`` from
# faking userinfo; the username side is ``*`` because ``:SECRET@`` —
# an EMPTY user — is still a live password (audit W8-r16).
_URL_CREDENTIAL_RE = re.compile(r"://[^/\s:@?#]*:[^@/\s?#]+@")
#: ``KEY``/``--flag`` shape for the left of a ``=`` list item — a bare
#: ``=`` inside a URL query (``?sslmode=require``) is NOT an assignment.
_ASSIGN_KEY_RE = re.compile(r"^-{0,2}[A-Za-z_][A-Za-z0-9_.-]*$")


def _is_credential_key(name: str) -> bool:
    lowered = str(name).strip().lower()
    return (
        lowered in _CREDENTIAL_KEYS_EXACT
        or lowered.endswith(_CREDENTIAL_KEY_SUFFIXES)
        or bool(_CREDENTIAL_BARE_RE.search(lowered))
    )


def _has_url_secret(value: Any) -> bool:
    return isinstance(value, str) and bool(_URL_CREDENTIAL_RE.search(value))


#: A credential URL at the START of an item — the item IS the secret
#: (whole redaction); a URL appearing mid-string goes through the
#: surgical pass instead.
_URL_CREDENTIAL_LEAD_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9.+-]*://[^/\s:@?#]*:[^@/\s?#]+@"
)
#: ``--flag=VALUE`` and ``--flag VALUE`` inside an opaque string —
#: ``-c 'exec srv --api-key K'`` (audit W8-r7). For the separated form
#: the value must not start with ``-`` — a following flag is not a
#: value.
#: ``--flag``/``-f`` token start inside an opaque string — the
#: lookbehind keeps glued words (``x--token``) from splitting
#: mid-token.
_FLAG_TOKEN_RE = re.compile(r"(?<![-\w.])(--?[A-Za-z_][A-Za-z0-9_.-]*)")
#: ``KEY=``/``KEY =`` assignment lead inside an opaque string — the
#: lookbehind keeps ``--flag=x`` out (the flag pass owns it); the
#: lookaheads keep ``x == y`` and ``k = --v`` out. The VALUE is located
#: by the word scanner, not a regex, so nested substitutions cannot
#: strand secret remainders (audit W8-r10).
_ASSIGN_LEAD_RE = re.compile(
    r"(?<![-\w.])([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(?!=)(?!--)"
)
#: ``Authorization: Bearer K``-style header credentials inside opaque
#: args — ``--header 'Authorization: Bearer K'`` (audit W8-r9).
#: ``api-key`` is the Azure-style header the egress gateway itself
#: understands (egress.py), so it is in the table too (audit W8-r10).
#: Only the LEAD is matched — header name, separator, optional scheme —
#: because the VALUE must be located by the shell-word scanner:
#: ``Bearer $(printf %s K)`` is one word, and a charset regex strands
#: ``(printf %s K)`` mounted (audit W8-r15).
_AUTH_LEAD_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key|x-auth-token"
    r"|api-key|apikey)(\s*[:=]\s*)"
    r"(?:(bearer|basic|token|digest|oauth)[ \t]+)?"
)
#: ``Digest`` authorization carries a comma-separated ``k=v`` list
#: whose ENTIRE value is credential material — username/realm/nonce/
#: uri/response. A single-fragment match redacts ``username=`` but
#: leaves the full ``response="..."`` mounted (audit W8-r11). The
#: pair list is consumed wholesale; the scheme word survives.
_AUTH_DIGEST_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization)(\s*[:=]\s*)digest\s+"
    r"(?:[A-Za-z_][A-Za-z0-9_-]*\*?\s*=\s*"
    r"(?:\\?\"(?:\\.|[^\"\\])*\\?\"|[^,\s\"]+)\s*,?\s*)+"
)
#: A bare auth scheme word with no header-name context —
#: ``Bearer eyJ…``. The value follows as a shell word; whether it is
#: credential-shaped is decided in the pass (audit W8-r15).
_AUTH_BARE_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic|oauth)[ \t]+")
#: ``scheme://user:pass@`` inside a longer string — only the userinfo
#: span is replaced, the URL shape survives.
_URL_USERINFO_SUB_RE = re.compile(r"(://)[^/\s:@?#]*:[^@/\s?#]+@")
#: ``<<TAG``/``<<-TAG``/``<<~TAG``/quoted heredoc openers inside an
#: opaque string — the BODY that follows is data, not syntax, and
#: carries credential material verbatim (``--api-key-file /dev/fd/3
#: 3<<'TAG'\nKEY\nTAG`` — audit W8-r13). Delimiters may be arbitrary
#: words (``RXY-KEY``), several heredocs queue on one command line
#: (``3<<A 4<<B`` — bodies read in order), and an unterminated body
#: runs to EOF (audit W8-r14).
_HEREDOC_RE = re.compile(
    r"<<([-~]?)\s*(?:'([^'\n]+)'|\"([^\"\n]+)\"|([^\s;|&<>()'\"]+))"
)


def _shell_word_end(
    text: str, start: int, stop_at_unclosed_quote: bool = False
) -> int:
    """End offset of the shell word starting at ``start`` — quoted
    spans (``'``, ``"``, ````, ANSI-C ``$'``), ``$(...)``/``${...}``
    (both nested), and ``<(...)``/``>(...)`` all count as part of the
    word; it ends at unquoted whitespace or a shell separator.

    Scanned with a real context stack, not a depth counter or a
    regex: a ``"`` inside ``$(...)`` does NOT close the outer quote —
    ``"$(printf "%s " K | tr -d ' ')"`` is ONE word and a naive
    quote-find strands ``K | tr -d ' ')"`` (audit W8-r13); ``${}``
    balances nested defaults (audit W8-r12); ``$(...)`` balances
    nested parens (audit W8-r10). ``stop_at_unclosed_quote`` handles
    values scanned inside an enclosing word — ``Bearer K" u``: the
    ``"`` is really the enclosing quote's CLOSER, so a quote context
    pushed mid-word that never closes ends the word at the quote
    (audit W8-r16). Glued quote segments like ``pre'x'y`` still
    balance and stay part of the word."""
    i = start
    n = len(text)
    stack: list[str] = []
    qpos: list[int] = []  # push index of each still-open quote context
    word = ""  # innermost bare word — case/esac keyword detection
    while i < n:
        c = text[i]
        top = stack[-1] if stack else ""
        if top == "'":
            # Plain single quotes — ``\`` is literal, only ``'`` ends.
            if c == "'":
                stack.pop()
                qpos.pop()
            else:
                word += c
            i += 1
            continue
        if top == "$'" or top == "`":
            # ANSI-C ``$'...'`` and backticks — escapes apply, the
            # same quote char ends them; nothing substitutes inside
            # either (a ``$(`` inside ``$'`` is literal text).
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == top[-1]:
                stack.pop()
                qpos.pop()
            else:
                word += c
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            # Escaped char — ``\$`` starts no substitution, ``\ ``
            # stays inside the word, ``\<newline>`` is a shell line
            # continuation (audit W8-r11). The escaped char is word
            # content (``ca\se`` is the word ``case``).
            word += text[i + 1]
            i += 2
            continue
        if top == '"':
            if c == '"':
                stack.pop()
                qpos.pop()
                i += 1
                continue
            # Substitutions still open inside ``"..."`` — their
            # interior quotes are balanced THERE, not here.
            if c == "$" and i + 1 < n and text[i + 1] in "({'":
                stack.append(("$" if text[i + 1] == "'" else "") + text[i + 1])
                if text[i + 1] == "'":
                    qpos.append(i + 1)
                word = ""
                i += 2
                continue
            if c == "`":
                stack.append("`")
                qpos.append(i)
                word = ""
                i += 1
                continue
            word += c
            i += 1
            continue
        # Word level or inside ``(``/``{``/``case`` — full shell
        # syntax. ``case``/``esac`` are tracked as contexts because a
        # case pattern's ``)`` is NOT the substitution's closer —
        # ``$(case x in x) K;; esac)`` would strand ``K;; esac)`` on a
        # naive paren count (audit W8-r14).
        if c == "$" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in "({'":
                stack.append(("$" if nxt == "'" else "") + nxt)
                if nxt == "'":
                    qpos.append(i + 1)
                word = ""
                i += 2
                continue
            word += c
            i += 1
            continue
        if c in "<>" and i + 1 < n and text[i + 1] == "(":
            # Process substitution ``<(cmd)``/``>(cmd)`` is a WORD,
            # not a redirect — it must be checked BEFORE the bare
            # ``<``/``>`` separator break below (audit W8-r11).
            stack.append("(")
            word = ""
            i += 2
            continue
        if c in " \t\n;|&<>(){}":
            if word:
                if (
                    word == "case"
                    and stack
                    and stack[-1] in ("(", "case")
                ):
                    stack.append("case")
                elif word == "esac" and stack and stack[-1] == "case":
                    stack.pop()
                word = ""
            if c == "(" or c == "{":
                stack.append(c)
            elif c == ")" and stack and stack[-1] == "(":
                stack.pop()
            elif c == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif not stack and c in " \t\n;|&<>":
                break
            i += 1
            continue
        if c == "'":
            stack.append("'")
            qpos.append(i)
        elif c == '"':
            stack.append('"')
            qpos.append(i)
        elif c == "`":
            stack.append("`")
            qpos.append(i)
            word = ""
        else:
            word += c
        i += 1
    if stop_at_unclosed_quote and qpos:
        # The outermost still-open quote is really the enclosing
        # word's closer — the word ends there, not at EOS.
        return qpos[0]
    return i


#: Bound on quoted/compound-value re-scrub depth — a pathological
#: config could nest quotes/``$(`` thousands deep and kill the
#: scrubber with a bare ``RecursionError``; beyond the cap the value
#: is treated as wholesale suspicious and dies (audit W8-r11 stream).
_SCRUB_RESCAN_DEPTH_CAP = 32
#: Depth bounds RECURSION, not WORK — nested compound values make flag
#: and assign passes revisit overlapping text and a 292-char input can
#: fan out to ~200k rescan calls (audit W8-r15). A per-string budget —
#: rescan call count AND total rescanned characters — fails closed
#: long before the amplification hurts.
_SCRUB_RESCAN_CALL_BUDGET = 2048


def _scrub_inline_secrets(
    text: str,
    _depth: int = 0,
    _budget: list[int] | None = None,
) -> str:
    """Redact credential material EMBEDDED inside an opaque string —
    ``args: ["-c", "exec server --api-key K"]`` or
    ``export TOKEN=x; srv`` hides secrets from the whole-item grammar,
    and the mounted config is readable whether or not MCP ever runs
    (audit W8-r7). Credential names consume the whole shell WORD that
    follows them (``$(...)``, ``${...}``, quotes and glued
    continuations count as one word — audit W8-r9/r10); non-credential
    names keep their value but it is recursively re-scrubbed inside.
    Same name tables as the whole-item grammar."""
    if _budget is None:
        _budget = [
            _SCRUB_RESCAN_CALL_BUDGET,
            max(1 << 16, len(text) * 8),
        ]
    _budget[0] -= 1
    _budget[1] -= len(text)
    if (
        _depth >= _SCRUB_RESCAN_DEPTH_CAP
        or _budget[0] < 0
        or _budget[1] < 0
    ):
        # Pathological nesting or a work-budget overrun — treat the
        # residue as opaque credential material rather than recurse
        # into a RecursionError or spin on amplified input.
        return "confined"

    def _cred_name(name: str) -> bool:
        lowered = name.lstrip("-").lower().replace("-", "_")
        return (
            _is_credential_key(lowered)
            or lowered in _CREDENTIAL_INDIRECTION_KEYS
        )

    def _rescan(value: str) -> str:
        """Re-scrub a compound value a NON-credential name points at —
        quoted spans keep their quotes; a ``$(...)``/mixed word is
        scrubbed inside wholesale (audit W8-r8/r9)."""
        if (
            len(value) > 1
            and value[:1] in ("'", '"', "`")
            and value.endswith(value[0])
        ):
            return (
                f"{value[0]}"
                f"{_scrub_inline_secrets(value[1:-1], _depth + 1, _budget)}"
                f"{value[0]}"
            )
        if any(c in value for c in ("'", '"', "$", "`")):
            return _scrub_inline_secrets(value, _depth + 1, _budget)
        return value

    def _flag_pass(src: str) -> str:
        out: list[str] = []
        pos = 0
        for match in _FLAG_TOKEN_RE.finditer(src):
            if match.start() < pos:
                # Inside a value word already consumed — a flag-looking
                # span in a scrubbed/rescanned value must not be
                # reprocessed and re-appended out of place.
                continue
            flag = match.group(1)
            j = match.end()
            eq = j < len(src) and src[j] == "="
            if eq:
                vstart = j + 1
            else:
                k = j
                while k < len(src):
                    if src[k] in " \t":
                        k += 1
                    elif src[k : k + 2] == "\\\n":
                        # ``\<newline>`` line continuation — the real
                        # value word is on the next line (audit W8-r11).
                        k += 2
                    elif src[k : k + 3] == "\\\r\n":
                        k += 3
                    else:
                        break
                # A separated value must exist and not be another flag
                # or a bare separator (r5 pair semantics kept);
                # ``<(``/``>(`` start process-substitution WORDS, not
                # redirects (audit W8-r11).
                if k == j or k >= len(src):
                    continue
                if src[k] in "-;|&" or (
                    src[k] in "<>"
                    and not (
                        k + 1 < len(src) and src[k + 1] == "("
                    )
                ):
                    continue
                vstart = k
            vend = _shell_word_end(src, vstart)
            if vend <= vstart:
                continue
            value = src[vstart:vend]
            out.append(src[pos:j])
            if _cred_name(flag):
                out.append("=confined" if eq else " confined")
            else:
                out.append(("=" if eq else src[j:vstart]) + _rescan(value))
            pos = vend
        out.append(src[pos:])
        return "".join(out)

    def _assign_pass(src: str) -> str:
        out: list[str] = []
        pos = 0
        for match in _ASSIGN_LEAD_RE.finditer(src):
            if match.start() < pos:
                continue  # inside an already-consumed value word
            j = match.end()
            vend = _shell_word_end(src, j)
            if vend <= j:
                continue
            value = src[j:vend]
            out.append(src[pos:j])
            if _cred_name(match.group(1)):
                out.append("confined")
            else:
                out.append(_rescan(value))
            pos = vend
        out.append(src[pos:])
        return "".join(out)

    def _heredoc_pass(src: str) -> str:
        """Redact heredoc BODIES — ``3<<'TAG'\nKEY\nTAG`` leaves the
        fd path scrubbed but the body verbatim (audit W8-r13). POSIX
        semantics honored: delimiters are arbitrary words
        (``RXY-KEY``); ``<<`` requires an EXACT terminator line,
        ``<<-`` strips leading tabs only, ``<<~`` strips leading
        whitespace; openers queued on one command line read their
        bodies in order (``3<<A 4<<B``); an unterminated body runs to
        EOF (audit W8-r14). Markers and terminator lines survive."""
        def _find_term(
            cursor: int, tag: str, lead: str, quoted: bool
        ) -> tuple[int, int] | None:
            r"""Terminator line span. A QUOTED delimiter compares
            physical lines; an UNQUOTED one compares LOGICAL lines —
            ``\<newline>`` joins inside the body first, so a physical
            ``EOF`` line that continues the previous one is content,
            not a terminator (audit W8-r16)."""
            if quoted:
                term = re.search(
                    r"(?m)^" + lead + re.escape(tag) + r"\r?$",
                    src[cursor:],
                )
                if term is None:
                    return None
                return cursor + term.start(), cursor + term.end()
            pat = re.compile(lead + re.escape(tag) + r"\r?")
            pos = cursor
            continued = False
            while pos <= len(src):
                nl = src.find("\n", pos)
                line = src[pos:] if nl == -1 else src[pos:nl]
                if not continued and pat.fullmatch(line):
                    return pos, pos + len(line)
                backslashes = len(line) - len(line.rstrip("\\"))
                continued = backslashes % 2 == 1
                if nl == -1:
                    break
                pos = nl + 1
            return None

        out: list[str] = []
        pos = 0
        matches = list(_HEREDOC_RE.finditer(src))
        idx = 0
        while idx < len(matches):
            m = matches[idx]
            idx += 1
            if m.start() < pos:
                continue
            nl = src.find("\n", m.end())
            if nl == -1:
                continue
            # A ``\<newline>`` at the end of the command line joins the
            # next physical line INTO it — the body begins after the
            # logical command line, not after the first newline.
            while True:
                seg = src[m.start() : nl]
                backslashes = len(seg) - len(seg.rstrip("\\"))
                if backslashes % 2 != 1:
                    break
                nxt = src.find("\n", nl + 1)
                if nxt == -1:
                    break
                nl = nxt
            # Every opener on the same command line queues a body —
            # they read in order after the line ends (audit W8-r14).
            queue = [m]
            while idx < len(matches) and matches[idx].start() < nl:
                queue.append(matches[idx])
                idx += 1
            out.append(src[pos : nl + 1])
            cursor = nl + 1
            for q in queue:
                flag, tag = q.group(1), next(
                    g for g in q.groups()[1:] if g is not None
                )
                quoted = q.group(2) is not None or q.group(3) is not None
                lead = r"[ \t]*" if flag == "~" else (r"\t*" if flag == "-" else "")
                tspan = _find_term(cursor, tag, lead, quoted)
                if tspan is None:
                    # No terminator — bash reads the body to EOF;
                    # everything after the command line is body
                    # (audit W8-r14).
                    out.append("confined\n")
                    cursor = len(src)
                    break
                body_end, term_end = tspan
                line_end = src.find("\n", term_end)
                if line_end == -1:
                    line_end = len(src)
                else:
                    line_end += 1
                out.append("confined\n")
                out.append(src[body_end:line_end])  # keep terminator
                cursor = line_end
            pos = cursor
        out.append(src[pos:])
        return "".join(out)

    def _value_end(src: str, start: int) -> int:
        """End of a header/bare-scheme value — always a shell word, so
        ``Bearer prefix$(printf %s K)`` dies whole (audit W8-r16).
        ``stop_at_unclosed_quote`` keeps a trailing unterminated quote
        — really the enclosing word's closer — from swallowing the
        rest of the string (``Bearer K" u`` stops at ``"``)."""
        return _shell_word_end(src, start, stop_at_unclosed_quote=True)

    def _auth_pass(src: str) -> str:
        """Header-named credentials — scheme-led (``Bearer K``) and
        naked (``X-Api-Key: RAWTOKEN``) values die as one shell word;
        the 4-char naked floor keeps ``authorization: no`` alive."""
        out: list[str] = []
        pos = 0
        for match in _AUTH_LEAD_RE.finditer(src):
            if match.start() < pos:
                continue
            vstart = match.end()
            vend = _value_end(src, vstart)
            if vend <= vstart:
                continue  # header word with no value
            if match.group(3) is None and vend - vstart < 4:
                continue  # naked floor
            out.append(src[pos:vstart])
            out.append("confined")
            pos = vend
        out.append(src[pos:])
        return "".join(out)

    def _bare_scheme_pass(src: str) -> str:
        """Scheme word without a header name — ``Bearer eyJ…``. The
        value must LOOK credential-shaped (a digit/symbol or serious
        length): ``Basic configuration`` is prose, not a credential
        (audit W8-r15)."""
        out: list[str] = []
        pos = 0
        for match in _AUTH_BARE_SCHEME_RE.finditer(src):
            if match.start() < pos:
                continue
            vstart = match.end()
            vend = _value_end(src, vstart)
            value = src[vstart:vend]
            if len(value) < 8 or (
                len(value) < 32 and not re.search(r"[^A-Za-z]", value)
            ):
                continue
            out.append(src[pos:vstart])
            out.append("confined")
            pos = vend
        out.append(src[pos:])
        return "".join(out)

    text = _flag_pass(text)
    text = _assign_pass(text)
    text = _heredoc_pass(text)
    text = _AUTH_DIGEST_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}Digest confined", text
    )
    text = _auth_pass(text)
    text = _bare_scheme_pass(text)
    return _URL_USERINFO_SUB_RE.sub(r"\g<1>confined:confined@", text)


def _scrub_credential_values(node: Any, _seen: set[int] | None = None) -> None:
    """Recursively redact credential-shaped scalars anywhere in a config
    tree — model entries, ``rag.embedding.api_key``, MCP-server ``env``
    maps AND env lists (``["GITHUB_TOKEN=…"]`` is a supported MCP config
    form, mcp/client.py:_normalize_server_config), run-together names
    like ``PGPASSWORD``, and URLs carrying userinfo passwords under
    non-credential names (``database_url``). Values become
    ``"confined"``; indirection resolvers (``*_env``/``*_file``) are
    blanked (audit W8-r3). YAML aliases make the tree a DAG — and a
    self-referencing anchor (``&x [*x]``) a real cycle; the ``_seen``
    id-set dedups shared nodes and breaks cycles, and traversal is
    ITERATIVE — an acyclic alias chain a thousand links deep must not
    RecursionError either (audit W8-r15/r16)."""
    if _seen is None:
        _seen = set()
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, (dict, list)):
            marker = id(cur)
            if marker in _seen:
                continue
            _seen.add(marker)
        if isinstance(cur, dict):
            for key, value in list(cur.items()):
                lowered = str(key).strip().lower()
                if isinstance(value, (dict, list)):
                    stack.append(value)
                    continue
                if lowered in _CREDENTIAL_INDIRECTION_KEYS:
                    del cur[key]
                elif _is_credential_key(lowered):
                    cur[key] = "confined"
                elif _has_url_secret(value):
                    # A BARE credential URL is a secret whole; a composite
                    # string carrying one (a launcher, a shell snippet)
                    # loses only the userinfo span (audit W8-r7).
                    if _URL_CREDENTIAL_LEAD_RE.match(str(value).strip()):
                        cur[key] = "confined"
                    else:
                        cur[key] = _scrub_inline_secrets(str(value))
                elif isinstance(value, str):
                    # Opaque strings can still carry credential material —
                    # ``command: "sh -c 'srv --token K'"`` (audit W8-r7).
                    cur[key] = _scrub_inline_secrets(value)
        elif isinstance(cur, list):
            for idx, item in enumerate(cur):
                if isinstance(item, str):
                    key, _eq, value = item.partition("=")
                    lowered_key = (
                        key.strip().lower().lstrip("-").replace("-", "_")
                    )
                    if (
                        _eq
                        and _ASSIGN_KEY_RE.match(key.strip())
                        and (
                            lowered_key in _CREDENTIAL_INDIRECTION_KEYS
                            or _is_credential_key(lowered_key)
                            or _has_url_secret(value)
                        )
                    ):
                        # ``KEY=VALUE`` env entries AND ``--flag=value`` args —
                        # only when the part before ``=`` is a real key/flag
                        # name (audit W8-r3/r4/r5).
                        cur[idx] = f"{key.strip()}=confined"
                    elif _has_url_secret(item):
                        # A positional arg carrying a credential URL — the
                        # ``=`` inside ``postgres://u:p@db/app?sslmode=require``
                        # is a QUERY parameter, not an assignment; the whole
                        # item is a secret either way (audit W8-r4/r6). When
                        # the URL is only PART of the item (a shell
                        # fragment), only its userinfo dies (W8-r7).
                        if _URL_CREDENTIAL_LEAD_RE.match(item.strip()):
                            cur[idx] = "confined"
                        else:
                            cur[idx] = _scrub_inline_secrets(item)
                    elif (
                        not _eq
                        and _ASSIGN_KEY_RE.match(item.strip())
                        and (
                            _is_credential_key(lowered_key)
                            or lowered_key in _CREDENTIAL_INDIRECTION_KEYS
                        )
                    ):
                        # Separated flag-value pairs —
                        # ``args: ["--api-key", "s3cr3t"]`` — keep the
                        # flag, redact the value that follows it (W8-r5).
                        # A following ``--`` item is a new flag, not a
                        # value — nothing to redact. The item must be a
                        # PURE flag spelling: a composite string like
                        # ``run --token=x`` happens to end in ``_token``
                        # and would otherwise eat the next item whole.
                        if idx + 1 < len(cur) and isinstance(
                            cur[idx + 1], str
                        ) and not str(cur[idx + 1]).startswith("--"):
                            cur[idx + 1] = "confined"
                    else:
                        # Opaque strings — ``-c`` payloads and launcher
                        # fragments — can carry flags/assignments/URLs the
                        # whole-item grammar never sees (audit W8-r7).
                        cur[idx] = _scrub_inline_secrets(item)
                    continue
                if isinstance(item, (dict, list)):
                    stack.append(item)


def _scrub_model_credentials(
    data: dict[str, Any], *, egress_port: int, env_model: str
) -> None:
    """Strip every credential-shaped field from the copied config and
    point the used model at the loopback egress gateway — the parent
    injects real auth on the upstream hop. Idempotent: safe to re-apply
    on the already-scrubbed child copy."""
    _scrub_credential_values(data)
    models = data.get("models")
    if not isinstance(models, dict):
        return
    gateway_url = f"http://127.0.0.1:{egress_port}" if egress_port else ""
    wanted = str(env_model or data.get("active_model") or "")
    if wanted and wanted not in models:
        # AgentV2 falls back to the active entry for an unknown name —
        # the rewrite must follow the same fallback.
        wanted = str(data.get("active_model") or "")
    for name, entry in models.items():
        if not isinstance(entry, dict):
            continue
        # The schema expects an api_key field — keep it present, redacted.
        entry["api_key"] = "confined"
        if wanted and str(name) == wanted and gateway_url:
            entry["base_url"] = gateway_url


def _prepare_child_data_dir(conf_dir: Path) -> Path:
    """Per-run config home under the drain-controlled state root — a
    SANITIZED copy of the worker's config.yaml so model resolution reads
    a real file. It is ro-bound into the sandbox; the confined turn can
    never write it (and can never leave a destination symlink for the
    parent to follow).

    Scrubbing happens HERE, before the file is ever mounted: an ro bind
    stops modification, not disclosure — a literal ``api_key`` readable
    under ``RXYCODE_TURN_CONFIG_SRC`` is still a leaked platform secret
    (audit W8-r1). A config the scrubber cannot parse is dropped entirely
    rather than mounted raw."""
    conf_dir.mkdir(parents=True, exist_ok=True)
    source_root = os.environ.get("RXYCODE_DATA_DIR", "").strip()
    if not source_root:
        return conf_dir
    source = Path(source_root) / "config.yaml"
    if not source.is_file():
        return conf_dir
    try:
        import yaml

        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        _LOG.warning(
            "turn config source unreadable; mounting an empty config", exc_info=True
        )
        data = {}
    _scrub_model_credentials(
        data,
        egress_port=_EGRESS_PORT,
        env_model=os.environ.get("RXYCODE_WORKER_MODEL", ""),
    )
    try:
        conf_dir.joinpath("config.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8"
        )
    except OSError:
        _LOG.warning("writing sanitized turn config failed", exc_info=True)
    return conf_dir


_USAGE_LINE = "__RXY_USAGE__"


async def _wait_child(
    proc: "asyncio.subprocess.Process",
    stderr_tail: list[bytes],
    usage_sink: dict[str, int] | None = None,
    proc_identity: Any | None = None,
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
        # Kill the whole tree, not only the supervisor: inside bwrap the
        # pid namespace + --die-with-parent already reaps descendants, but
        # on a namespace-less host (Windows dev, degraded runners) a
        # spawned grandchild would otherwise survive as residue
        # (audit W8-r2: cancellation must leave nothing running).
        # The sweep goes through the psutil handle captured AT SPAWN —
        # it pins (pid, create_time), so a reaped-then-reused pid reads
        # is_running()=False and we never enumerate or kill an unrelated
        # replacement process's children (audit W8-r3).
        descendants: list[Any] = []
        if proc.returncode is None and proc_identity is not None:
            try:
                if proc_identity.is_running():
                    descendants = proc_identity.children(recursive=True)
            except Exception:
                descendants = []
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        for kid in descendants:
            try:
                kid.kill()
            except Exception:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception:
            pass
        for kid in descendants:
            try:
                kid.wait(timeout=5)
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


class _RunPaused(BaseException):
    """The run parked itself for a durable approval: the ask is persisted,
    the lease already released by the parent-side ctl op. Raising through
    the whole agent stack unwinds the turn WITHOUT writing — BaseException
    so `except Exception` handlers in the runtime cannot swallow it."""


class _ResumeSettled(Exception):
    """A resume claim settled without spawning a child — raised inside
    ``execute_run``'s try so the terminal verdict still flows through the
    SHARED finalize path (metering flush, terminal usage upsert,
    attribution notes, span close, quota release, notify,
    commit_terminal). An early return would orphan the original turn's
    real spend and skip the lease-fenced terminal write (audit W8-r3)."""

    def __init__(self, status: str, detail: str = "") -> None:
        super().__init__(detail or status)
        self.status = status
        self.detail = detail


class _CtlApproval:
    """ApprovalBroker over the parent control channel (confined turns only).

    The durable ask lives on the parent: request_approval() persists the
    exact call (tenant/run/call/attempt + raw arguments), flips the run to
    ``waiting_approval`` and releases the lease. The child then unwinds
    via ``_RunPaused``; a fresh confined process executes exactly the
    stored call after a human approval re-queues the run.
    """

    def __init__(self, channel: Any, *, run_id: str, workdir: Path) -> None:
        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalBroker

        class _Broker(ApprovalBroker):
            async def _ask(inner_self, request: Any) -> Any:  # noqa: ANN001
                from RxyCode.RxyCode1_1_0.core.safety.approval import (
                    ApprovalDecision,
                )

                args = dict(request.arguments or {})
                command = str(args.get("command") or args.get("cmd") or "")
                scope = str(request.risk.name.lower())
                if request.gate_blocked_paths:
                    scope = f"{scope}:write-path-gate"
                deadline = (
                    datetime.now(timezone.utc).timestamp() + _APPROVAL_DEADLINE_S
                )
                result = await asyncio.to_thread(
                    channel.pause_approval,
                    source_call_id=str(request.call_id or request.approval_id),
                    tool=str(request.tool_name),
                    permission_scope=scope,
                    arguments=args,
                    deadline=datetime.fromtimestamp(
                        deadline, tz=timezone.utc
                    ).isoformat(),
                    workdir=str(workdir),
                    command=command,
                )
                if result.get("asked"):
                    raise _RunPaused()
                reason = str(result.get("reason") or "")
                if reason == "already_authorized":
                    return ApprovalDecision.APPROVED
                # no_broker / stale / any refused ask: fail closed — the
                # call simply never executes inside the sandbox.
                return ApprovalDecision.REJECTED

        self._broker = _Broker()
        self._run_id = run_id

    def broker(self) -> Any:
        return self._broker


class _ChannelJournal:
    """RemoteJournalAdapter over the parent control channel.

    The approval-resume reservation lives in parent-owned storage behind
    ctl ops — a workspace wipe inside the sandbox can never erase it and
    win a second side effect (audit W8-r1). Same method surface as
    ``RemoteJournalAdapter`` so ``_execute_approved_call`` is journal-
    location agnostic.
    """

    def __init__(self, channel: Any) -> None:
        self._channel = channel

    def state(self, *, attempt_id: str, call_id: str) -> str:
        if not attempt_id or not call_id:
            return "not_started"
        return self._channel.journal_state(
            attempt_id=str(attempt_id), call_id=str(call_id)
        )

    def reserve(self, *, attempt_id: str, call_id: str, tool: str, args: Any) -> Any:
        from RxyCode.RxyCode1_1_0.execution.tool_journal import JournalReservation

        result = self._channel.journal_reserve(
            attempt_id=str(attempt_id),
            call_id=str(call_id),
            tool=str(tool),
            args=dict(args or {}),
        )
        action = str(result.get("action") or "uncertain")
        return JournalReservation(action=action, result=result.get("result"))  # type: ignore[arg-type]

    def complete(
        self, *, attempt_id: str, call_id: str, tool: str, args: Any, result: Any
    ) -> str:
        # The journal cleans to its own max_result_chars parent-side; cap
        # the wire payload below the ctl frame limit first.
        return self._channel.journal_complete(
            attempt_id=str(attempt_id),
            call_id=str(call_id),
            tool=str(tool),
            args=dict(args or {}),
            result=str(result if result is not None else "")[:400_000],
        )


#: Approval asks die with the run; the deadline bounds how long a run may
#: sit in waiting_approval before the service expires it.
_APPROVAL_DEADLINE_S = 3600.0

#: Journal-keyed durable call ids must match ``call_[0-9a-f]{32}`` — the
#: shape ``remote_call_key`` accepts. Raw orchestrator/model ids (bare hex,
#: provider strings like ``call_Xyz9``) are hashed into this shape by the
#: trusted parent before they reach the durable approval row.
_DURABLE_CALL_ID_RE = re.compile(r"^call_[0-9a-f]{32}$")

#: Control-plane event namespaces a confined child may NEVER mint — they
#: are authored exclusively by the parent/API (audit W8-r2). A forged
#: ``turn.paused`` would fake the old-namespace-dead proof a resume
#: claimant polls for; a forged ``steer.accepted``/``child.cancel`` row
#: would inject commands back into the consume loop; a forged
#: ``approval.requested`` would corrupt the resume lookup. The child's
#: legitimate rows are ``notify.*``/``assistant.*``/``tool.*``/
#: ``question.*``/``usage.delta``/``telemetry.span`` — none live here.
_CHILD_EMIT_RESERVED_PREFIXES = ("turn.", "run.", "approval.", "worker.")
_CHILD_EMIT_RESERVED_EXACT = frozenset(
    {"usage.attribution", "steer.accepted", "child.cancel"}
)


def _task_turn_env(workdir: Path) -> dict[str, str]:
    """Task-private development environment INSIDE the sandbox.

    HOME, caches, package-manager and venv state all live under the
    workspace — the only rw mount besides the private /tmp — so ``edit``,
    ``bash`` and ``python`` operate on the SAME real paths with the same
    write domain (allowed_write_paths is derived from this list).
    """
    home = workdir / ".home"
    return {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PIP_CACHE_DIR": str(home / ".cache" / "pip"),
        "npm_config_cache": str(home / ".cache" / "npm"),
        "UV_CACHE_DIR": str(home / ".cache" / "uv"),
        "TMPDIR": "/tmp",
    }


def _writable_domain(workdir: Path) -> list[str]:
    """The sandbox-real write domain for in-turn path checks — the mounted
    rw paths, not host rules. edit/bash/python enforce against this set."""
    return [str(workdir), str(workdir / ".home"), "/tmp"]


def _lease_fenced(
    database_url: str, run_id: str, worker_id: str, epoch: int
) -> bool:
    """True only while THIS claim still owns the run: right owner, right
    epoch, a live (non-cancel-requested) status and an unexpired lease.
    Approval rows stay ``approved`` across a cancel — the lease check is
    what stops a late resume from executing (audit W8-r1)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status, lease_owner, lease_epoch, lease_until "
                    "FROM runs WHERE id = :rid"
                ),
                {"rid": run_id},
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return False
    status, owner, lease_epoch, lease_until = row
    if str(status or "") not in {"leased", "running"}:
        return False
    if str(owner or "") != str(worker_id) or int(lease_epoch or 0) != int(epoch):
        return False
    until = _aware_dt(lease_until)
    return until is not None and until >= datetime.now(timezone.utc)


def _approval_call_binding(
    database_url: str,
    run_id: str,
    *,
    attempt_id: str,
    call_id: str,
) -> dict[str, Any] | None:
    """The stored approval.requested payload for (attempt_id, call_id) of
    THIS run — or None when the pair was never durably asked.

    The journal ops bind against this row so a confined child can only
    ever journal the exact approved call it was granted, never a pair it
    minted itself (audit W8-r2)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT payload FROM run_events WHERE run_id = :rid "
                    "AND type = 'approval.requested' "
                    "AND payload->>'attempt_id' = :att "
                    "AND payload->>'call_id' = :cid LIMIT 1"
                ),
                {"rid": run_id, "att": attempt_id, "cid": call_id},
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return None
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    return dict(payload) if isinstance(payload, dict) else None


def _old_namespace_alive(state_root: Path | None, sandbox_id: str) -> bool | None:
    """Positive-liveness probe for the PREVIOUS claim's drain, via its
    per-run control socket on this host's state root.

    ONLY ``True`` is meaningful — the socket still answers, so the old
    drain is alive and its confined child may still run. ``False`` and
    ``None`` are INCONCLUSIVE, never proof of death: the ctl dir is
    rw-bound into the sandbox so a live child can unlink its own socket,
    and a claimant on another host lacks the old host's local directory
    while the old worker is still alive (audit W8-r3). The only trusted
    teardown proof is the parent-authored ``turn.paused`` marker."""
    if not state_root or not sandbox_id:
        return None
    ctl_dir = Path(state_root) / f"{sandbox_id}-ctl"
    if not ctl_dir.exists():
        return False
    sock_path = ctl_dir / "ctl.sock"
    if not sock_path.exists():
        return False
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except (AttributeError, OSError):
        return None
    try:
        probe.settimeout(0.5)
        probe.connect(str(sock_path))
    except (ConnectionRefusedError, FileNotFoundError):
        return False
    except OSError:
        return None
    finally:
        try:
            probe.close()
        except Exception:
            pass
    return True


def _safe_unlink_inside(dir_path: Path, name: str) -> None:
    """Unlink ``dir_path/name`` — never through a swapped parent symlink.

    A confined child can plant ``.data -> /host/path`` inside its
    writable workspace and a naive ``(ws_data / "config.yaml").unlink``
    by the UNCONFINED parent would then delete a host file (audit
    W8-r5). POSIX takes the atomic route — ``O_NOFOLLOW|O_DIRECTORY``
    open + ``dir_fd`` unlink acts on the opened inode, immune to a
    later swap; elsewhere (Windows) a realpath equality check narrows
    the race to the final syscall — unprivileged symlink creation makes
    the residual window hard to hit there."""
    if os.unlink in getattr(os, "supports_dir_fd", ()):
        try:
            fd = os.open(
                str(dir_path),
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError:
            # Missing dir — or a symlink refused by O_NOFOLLOW; either
            # way there is nothing safe to unlink by path.
            return
        try:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(fd)
        return
    try:
        real_dir = Path(os.path.realpath(dir_path))
        expected = Path(os.path.realpath(dir_path.parent)) / dir_path.name
        if real_dir != expected:
            return
        (dir_path / name).unlink(missing_ok=True)
    except OSError:
        pass


def _run_journal_dir(state_root: Path, tenant_id: str, run_id: str) -> Path:
    """Parent-owned at-most-once journal for the run — keyed by RUN, not
    by the per-claim sandbox id: a reclaimed run must see the previous
    claimant's reservations or the same approved call executes twice
    (audit W8-r2). Lives outside every writable mount; the child reaches
    it only through the journal_* ctl ops."""
    return Path(state_root) / "journals" / str(tenant_id) / str(run_id)


def _remove_claim_dirs(claim_dirs: Iterable[Path]) -> None:
    """Remove every per-claim state_root dir — conf copy, ctl sockets,
    overlay upper/work/seed layers — after the child is dead and the
    record destroyed (audit W8-r6: ``retain=False`` must retain
    NOTHING). Best-effort: a busy or vanished dir is left for the next
    sweeper, never escalated into a teardown failure. The run-keyed
    journal dir is deliberately NOT in this list — it must survive the
    claimant for at-most-once replay."""
    for _dir in claim_dirs:
        try:
            shutil.rmtree(_dir, ignore_errors=True)
        except Exception:
            pass


def _tool_call_failed(text: Any) -> bool:
    """True when an orchestrator result string is a non-executed/error
    marker rather than real tool output — gate refusals, missing tools,
    workflow/search/download errors, timeouts, cancellations, user
    rejections and dry-run markers.

    Journal completion is replay safety, not success; the stored outcome
    is classified separately (audit W8-r2). The classification shares
    the codebase's canonical prefix tables (``log.log_helpers``) so
    registered-tool formats like ``[workflow error:`` cannot slip
    through as success (audit W8-r3) — but restricted to what is
    actually a TOOL error format: every ``[``-bracketed prefix is the
    designed failure convention (``tools/bash.py``: "Tool recovery
    classifies the stable [error...] prefix"), while bare answer-text
    prefixes like ``error:``/``failed to `` collide with ordinary
    program output and would falsely terminalize a successful call
    (audit W8-r4/r5). The only bare-text forms kept are this codebase's
    real tool error strings — the download/installer family. An EMPTY
    stored result is not proof of failure — the call ran and printed
    nothing."""
    stripped = str(text).strip()
    if not stripped:
        return False
    try:
        from RxyCode.RxyCode1_1_0.log.log_helpers import (
            _CANCELLED_RESULT_PREFIXES,
            _FAILED_RESULT_PREFIXES,
            _TIMEOUT_RESULT_PREFIXES,
        )
    except Exception:
        from log.log_helpers import (  # type: ignore
            _CANCELLED_RESULT_PREFIXES,
            _FAILED_RESULT_PREFIXES,
            _TIMEOUT_RESULT_PREFIXES,
        )

    bracketed = tuple(
        p
        for p in (
            _CANCELLED_RESULT_PREFIXES
            + _TIMEOUT_RESULT_PREFIXES
            + _FAILED_RESULT_PREFIXES
        )
        if p.startswith("[")
    )
    lowered = stripped.lower()
    return lowered.startswith(bracketed + _TOOL_RESULT_BARE_ERRORS)


#: Bare-text designed tool errors in this codebase — file_download /
#: download_tool / installer / mcp_manager return these unbracketed.
#: Everything else bare (``error:``, ``failed to `` generically) is
#: ordinary program output, not a failure verdict (audit W8-r5).
_TOOL_RESULT_BARE_ERRORS = (
    "download failed:",
    "error: file exceeded",
    "failed to install",
    "failed to add mcp",
    "failed to save config",
)


def _aware_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _paused_marker_seen(database_url: str, run_id: str, approval_id: str) -> bool:
    """The drain emits ``turn.paused`` only AFTER its confined child has
    exited — the durable proof the old namespace stopped before a new
    claimant may replay the approved call (audit W8-r1)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM run_events WHERE run_id = :rid "
                    "AND type = 'turn.paused' "
                    "AND payload->>'approval_id' = :aid LIMIT 1"
                ),
                {"rid": run_id, "aid": approval_id},
            ).first()
    finally:
        engine.dispose()
    return row is not None


def _pending_resume(
    database_url: str,
    tenant_id: str,
    run_id: str,
    *,
    state_root: Path | None = None,
) -> dict[str, Any] | None:
    """If the run's latest durable approval was APPROVED, return its stored
    call record for the confined resume child; else None.

    ``state_root`` lets the teardown barrier probe the OLD claim's
    control socket when the turn.paused marker never arrives.

    The only path from ``waiting_approval`` back to a claimable status is
    ``decide_approval(... approved)`` -> ``pending`` — so a claimed run
    whose newest ``approval.requested`` is approved is a resume, not a
    fresh turn."""
    approval_id = _latest_requested_approval_id(database_url, run_id)
    if not approval_id:
        return None
    record = _resume_state(database_url, tenant_id, run_id, approval_id)
    if record is None:
        return None
    # Old-worker/new-claim handoff: approve->pending can be claimed while
    # the previous confined child is still unwinding. Wait (bounded) for
    # the old drain's post-exit ``turn.paused`` marker — child-mintable
    # namespaces are denied by _emit, so the marker is parent-authored
    # teardown proof (audit W8-r2) and the ONLY proof accepted: an absent
    # or refused ctl socket proves nothing — the child owns its ctl dir
    # and can unlink it while staying alive, and a foreign claimant may
    # lack the host-local path entirely (audit W8-r3). The socket probe
    # survives only to LOG a still-answering listener; on budget expiry
    # without the marker the verdict is teardown_unproven and the caller
    # settles recovery_required rather than executing beside an unproven
    # namespace.
    import time as _time

    deadline = _time.monotonic() + _LEASE_IO_BUDGET
    while not _paused_marker_seen(database_url, run_id, approval_id):
        if _time.monotonic() >= deadline:
            alive = _old_namespace_alive(
                state_root, str(record.get("sandbox_id") or "")
            )
            _LOG.warning(
                "run %s: no turn.paused marker for approval %s (old "
                "namespace probe: %s) — teardown unproven; refusing to "
                "resume beside a possibly-live confined child",
                run_id,
                approval_id,
                "still alive"
                if alive
                else ("unprobeable" if alive is None else "socket absent"),
            )
            return {"teardown_unproven": True, **record}
        _time.sleep(0.5)
    return record


def _resume_state(
    database_url: str, tenant_id: str, run_id: str, approval_id: str
) -> dict[str, Any] | None:
    """Resolve an approved approval into the stored call — bound to THIS
    run (an approval id from another run refuses)."""
    from rxycode_server.approvals.service import get_approval

    record = get_approval(database_url, tenant_id=tenant_id, approval_id=approval_id)
    if record is None or record["run_id"] != run_id:
        return None
    if record["status"] != "approved":
        return None
    return record


def _latest_requested_approval_id(database_url: str, run_id: str) -> str:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT payload->>'approval_id' AS aid FROM run_events "
                    "WHERE run_id = :rid AND type = 'approval.requested' "
                    "ORDER BY seq DESC LIMIT 1"
                ),
                {"rid": run_id},
            ).first()
    finally:
        engine.dispose()
    return str(row[0] or "") if row else ""


def _ctl_handlers(
    cfg: "WorkerConfig",
    *,
    tenant_id: str,
    run_id: str,
    epoch: int,
    workdir: Path,
    journal_dir: Path,
    paused: Any,
    paused_info: dict[str, Any],
    sandbox_id: str = "",
) -> dict[str, Any]:
    """Parent-side ops for one run's control socket.

    Every handler is bound to this drain's (tenant_id, run_id, worker_id,
    epoch): the confined child can only ever act on its own run, and
    lease-fenced service calls still refuse once the claim is gone."""

    def _emit(args: dict[str, Any]) -> dict[str, Any]:
        from rxycode_server.events.store import append_event

        event_type = str(args.get("type") or "")[:120]
        if (
            event_type.startswith(_CHILD_EMIT_RESERVED_PREFIXES)
            or event_type in _CHILD_EMIT_RESERVED_EXACT
        ):
            # Reserved control-plane namespaces are parent-authored only —
            # a child-forged turn.paused/steer.accepted is an injection,
            # not an event. Deny without writing.
            return {"seq": 0, "denied": "reserved-namespace"}
        seq = append_event(
            cfg.database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=event_type,
            payload=dict(args.get("payload") or {}),
        )
        return {"seq": int(seq or 0)}

    def _load_run(args: dict[str, Any]) -> dict[str, Any]:
        from rxycode_server.runs.service import load_run

        loaded = load_run(cfg.database_url, run_id)
        # Only the fields the turn legitimately needs — the row can carry
        # scheduling internals the child has no business reading.
        return {
            "message": str(loaded.get("message") or ""),
            "session_id": str(loaded.get("session_id") or ""),
            "target_id": str(loaded.get("target_id") or ""),
            "permission_profile": str(loaded.get("permission_profile") or ""),
        }

    def _commands(args: dict[str, Any]) -> dict[str, Any]:
        from rxycode_worker.agent_events import load_command_events

        events = load_command_events(
            cfg.database_url, run_id, int(args.get("after_seq") or 0)
        )
        return {"events": events}

    def _pause_approval(args: dict[str, Any]) -> dict[str, Any]:
        from rxycode_server.approvals.service import request_approval

        try:
            deadline_raw = str(args.get("deadline") or "")
            deadline = datetime.fromisoformat(deadline_raw)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
        except ValueError:
            deadline = datetime.now(timezone.utc)
        # Must match the journal's ``att_[0-9a-f]{32}`` attempt-id contract —
        # a shorter id would make every resume fail closed at reserve().
        attempt_id = f"att_{uuid.uuid4().hex}"
        # The confined child supplies the raw orchestrator/model call id; the
        # durable journal key is derived HERE (trusted parent) so a child can
        # never mint a ``call_*`` key that collides with another run's call.
        # Idempotent: a source already in durable shape is used as-is.
        source_call_id = str(
            args.get("source_call_id") or args.get("call_id") or ""
        )[:200]
        if source_call_id and _DURABLE_CALL_ID_RE.fullmatch(source_call_id):
            durable_call_id = source_call_id
        else:
            seed = source_call_id or uuid.uuid4().hex
            durable_call_id = (
                "call_"
                + hashlib.sha256(f"{run_id}:{seed}".encode("utf-8")).hexdigest()[:32]
            )
        try:
            result = request_approval(
                cfg.database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                call_id=durable_call_id,
                tool=str(args.get("tool") or "")[:80],
                permission_scope=str(args.get("scope") or "")[:80],
                arguments=dict(args.get("arguments") or {}),
                deadline=deadline,
                worker_id=cfg.worker_id,
                epoch=epoch,
                attempt_id=attempt_id,
                command=str(args.get("command") or "")[:20000],
                workdir=str(workdir),
                source_call_id=source_call_id,
                sandbox_id=sandbox_id,
            )
        except Exception as exc:
            # Stale lease / already-decided: the ask did NOT park the run.
            return {
                "asked": False,
                "reason": f"refused:{type(exc).__name__}",
            }
        # The run is now waiting_approval and our lease is released — flag
        # it BEFORE telling the child so the drain's post-wait check can
        # never race the unwind into a spurious settle.
        paused_info["approval_id"] = str(result.get("approval_id") or "")
        paused.set()
        return {
            "asked": True,
            "approval_id": str(result.get("approval_id") or ""),
            "attempt_id": attempt_id,
        }

    def _resume_state_op(args: dict[str, Any]) -> dict[str, Any]:
        record = _resume_state(
            cfg.database_url,
            tenant_id,
            run_id,
            str(args.get("approval_id") or ""),
        )
        if record is None:
            return {"record": None}
        # Claim fence: the stored call may execute only while THIS claim
        # still owns the run. approve→claim→cancel must not let a late
        # resume_state fetch execute — the row stays "approved" but the
        # lease is gone, so nothing is returned (audit W8-r1).
        if not _lease_fenced(cfg.database_url, run_id, cfg.worker_id, epoch):
            return {"record": None}
        # Bound copy for the confined resume child — never the raw row.
        return {
            "record": {
                "approval_id": str(record.get("approval_id") or ""),
                "run_id": str(record.get("run_id") or ""),
                "call_id": str(record.get("call_id") or ""),
                "attempt_id": str(record.get("attempt_id") or ""),
                "tool": str(record.get("tool") or ""),
                "command": str(record.get("command") or ""),
                "workdir": str(record.get("workdir") or ""),
                "source_call_id": str(record.get("source_call_id") or ""),
                "arguments": dict(record.get("arguments") or {}),
            }
        }

    def _journal_adapter() -> Any:
        """The approval-resume journal lives in PARENT-OWNED state — never
        inside the child's writable workspace, where an approved command
        could erase the reservation and force a second side effect
        (audit W8-r1)."""
        from RxyCode.RxyCode1_1_0.execution.tool_journal import (
            RemoteJournalAdapter,
            ToolExecutionJournal,
        )

        return RemoteJournalAdapter(ToolExecutionJournal(str(journal_dir)))

    def _journal_state_op(args: dict[str, Any]) -> dict[str, Any]:
        state = _journal_adapter().state(
            attempt_id=str(args.get("attempt_id") or ""),
            call_id=str(args.get("call_id") or ""),
        )
        return {"state": str(state)}

    def _journal_reserve(args: dict[str, Any]) -> dict[str, Any]:
        # Two fences before a side-effect grant (audit W8-r2):
        # 1. the claim must still own the run — a child that lost its
        #    lease or got cancelled between resume_state and reserve may
        #    never execute the stored call;
        # 2. (attempt_id, call_id, tool, args) must BE this run's stored
        #    approval — without the binding a child could reserve a
        #    fabricated call under journal-valid ids, or the real pair
        #    with swapped args.
        bound = _approval_call_binding(
            cfg.database_url,
            run_id,
            attempt_id=str(args.get("attempt_id") or ""),
            call_id=str(args.get("call_id") or ""),
        )
        if bound is None or not _lease_fenced(
            cfg.database_url, run_id, cfg.worker_id, epoch
        ):
            return {"action": "refused", "result": None}
        expected_args = dict(bound.get("arguments") or {})
        if str(bound.get("command") or "") and "command" not in expected_args:
            expected_args["command"] = str(bound["command"])
        from RxyCode.RxyCode1_1_0.execution.tool_journal import (
            arguments_digest,
        )

        child_args = dict(args.get("args") or {})
        if (
            str(bound.get("tool") or "") != str(args.get("tool") or "")
            or arguments_digest(expected_args) != arguments_digest(child_args)
        ):
            return {"action": "refused", "result": None}
        reservation = _journal_adapter().reserve(
            attempt_id=str(args.get("attempt_id") or ""),
            call_id=str(args.get("call_id") or ""),
            tool=str(args.get("tool") or ""),
            args=child_args,
        )
        return {"action": str(reservation.action), "result": reservation.result}

    def _journal_complete(args: dict[str, Any]) -> dict[str, Any]:
        # Completing only records an outcome, so the lease may be gone —
        # but the pair must still be this run's stored approval.
        bound = _approval_call_binding(
            cfg.database_url,
            run_id,
            attempt_id=str(args.get("attempt_id") or ""),
            call_id=str(args.get("call_id") or ""),
        )
        if bound is None:
            return {"result": "", "refused": True}
        cleaned = _journal_adapter().complete(
            attempt_id=str(args.get("attempt_id") or ""),
            call_id=str(args.get("call_id") or ""),
            tool=str(args.get("tool") or ""),
            args=dict(args.get("args") or {}),
            result=str(args.get("result") or ""),
        )
        return {"result": cleaned}

    return {
        "emit": _emit,
        "load_run": _load_run,
        "commands": _commands,
        "pause_approval": _pause_approval,
        "resume_state": _resume_state_op,
        "journal_state": _journal_state_op,
        "journal_reserve": _journal_reserve,
        "journal_complete": _journal_complete,
    }


def _approval_args(record: dict[str, Any]) -> dict[str, Any]:
    """The exact args the approved call replays with — stored verbatim
    arguments plus the command field when the schema keeps it separate."""
    args = dict(record.get("arguments") or {})
    if str(record.get("command") or "") and "command" not in args:
        args["command"] = str(record["command"])
    return args


def _journal_result(journal_dir: Path, record: dict[str, Any]) -> str:
    """Stored result text for a COMPLETED approved call, fetched
    parent-side. Reads state first so a non-completed lookup can never
    create a reservation as a side effect."""
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )

    adapter = RemoteJournalAdapter(ToolExecutionJournal(str(journal_dir)))
    state = adapter.state(
        attempt_id=str(record.get("attempt_id") or ""),
        call_id=str(record.get("call_id") or ""),
    )
    if state != "completed":
        return ""
    reservation = adapter.reserve(
        attempt_id=str(record.get("attempt_id") or ""),
        call_id=str(record.get("call_id") or ""),
        tool=str(record.get("tool") or ""),
        args=_approval_args(record),
    )
    if reservation.action == "reuse":
        return str(reservation.result or "")
    return ""


def _merge_turn_config(dst: Path, workdir: Path) -> None:
    """Merge the sandbox-real write domain into the copied config.

    Path checks inside the turn must evaluate the SAME real paths the
    mounts expose — the workspace, its task-private home, and the private
    /tmp — never host rules. ``execution.os_sandbox`` is forced off: this
    process IS the sandbox; a nested wrap would only double-mount or fail.

    Model credentials are scrubbed for every entry (api_key/api_key_env/
    api_key_secret): the platform key must not exist inside the sandbox —
    the used model's base_url is rewritten to the loopback egress port and
    the parent injects real auth on the upstream hop.
    """
    try:
        import yaml
    except ImportError:
        return
    try:
        data = yaml.safe_load(dst.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    if not isinstance(data, dict):
        return
    safety = data.setdefault("safety", {})
    if isinstance(safety, dict):
        # A confined turn NEVER runs gate-disabled: the copied config could
        # carry a local developer's safety.enabled=false, which inside the
        # sandbox would silently skip the approval path entirely (Full is
        # implemented as permission_mode=full_auto — never as this switch).
        safety["enabled"] = True
        extra = safety.get("allowed_write_paths")
        merged = list(extra) if isinstance(extra, list) else []
        for path in _writable_domain(workdir):
            if path not in merged:
                merged.append(path)
        safety["allowed_write_paths"] = merged
    execution = data.setdefault("execution", {})
    if isinstance(execution, dict):
        execution["workspace_root"] = str(workdir)
        os_sandbox = execution.setdefault("os_sandbox", {})
        if isinstance(os_sandbox, dict):
            os_sandbox["enabled"] = False
    # Defense in depth: the mounted source was already sanitized by the
    # parent — re-scrub so a missed path can never carry a key inside.
    _scrub_model_credentials(
        data,
        egress_port=int(os.environ.get("RXYCODE_EGRESS_PORT", "0") or 0),
        env_model=os.environ.get("RXYCODE_WORKER_MODEL", ""),
    )
    try:
        dst.write_text(yaml.safe_dump(data), encoding="utf-8")
    except OSError:
        _LOG.warning("turn config merge failed", exc_info=True)


async def _resume_turn(
    *,
    channel: Any,
    run_id: str,
    tenant_id: str,
    workdir: Path,
    result_path: Path,
) -> int:
    """Confined resume child: replay EXACTLY the stored approved call.

    The parent already verified the approval row (tenant-bound, status
    ``approved``) and re-fetched the stored state; this process reads it
    again through the channel so the executed call is the persisted one —
    never anything the caller claimed. Journal state decides idempotence:
    a ``completed``/``unknown`` call is NOT re-run.
    """
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": "failed",
        "error": "",
        "tokens": 0,
    }
    journal = _ChannelJournal(channel)
    try:
        approval_id = os.environ.get("RXYCODE_TURN_APPROVAL", "").strip()
        state = await asyncio.to_thread(channel.resume_state, approval_id)
        record = dict(state.get("record") or {})
        if not record or str(record.get("run_id") or "") != run_id:
            result["error"] = "approval not found, not approved, or not bound to this run"
        else:
            attempt_id = str(record.get("attempt_id") or "")
            call_id = str(record.get("call_id") or "")
            # The already-approved call replays through the same
            # orchestrator under a grant broker (installed inside
            # _execute_approved_call): the human decided — re-asking
            # would deadlock — while every real gate and the kernel
            # boundary stay in force. reserve() decides idempotence:
            # completed -> reuse the STORED outcome (success or error);
            # anything else unresolvable -> refuse, never re-execute.
            emit = _RunEmit("", tenant_id, run_id, emitter=channel.emit)
            emit._append(
                "tool.call",
                {
                    "call_id": call_id,
                    "attempt_id": attempt_id,
                    "tool": str(record.get("tool") or ""),
                    "resumed": True,
                },
            )
            ok, text_out = await _execute_approved_call(
                record, workdir, emit, journal
            )
            result["status"] = "succeeded" if ok else "failed"
            if not ok:
                result["error"] = str(text_out)[:1500]
            if text_out:
                emit._append(
                    "tool.result",
                    {
                        "call_id": call_id,
                        "attempt_id": attempt_id,
                        "preview": str(text_out)[:2000],
                        "resumed": True,
                    },
                )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:1500]
    try:
        result_path.write_text(
            json.dumps(result) + "\n", encoding="utf-8"
        )
    except Exception:
        _LOG.warning("run %s: resume result write failed", run_id, exc_info=True)
    return 0


async def _execute_approved_call(
    record: dict[str, Any], workdir: Path, emit: Any, journal: Any
) -> tuple[bool, str]:
    """Execute the stored call through the SAME ToolOrchestrator every
    surface uses — blacklist, write-path gate and audit intact; approval
    was already granted (the grant broker answers prompts).

    Returns ``(ok, text)``: journal completion is replay safety only —
    a stored ``[error:``/``[blocked:`` result means the approved call did
    NOT produce its effect and the run must settle failed, whether the
    result came back now or was reused from a prior completion
    (audit W8-r2).

    ``journal`` is the at-most-once reservation — a ``_ChannelJournal``
    in the confined child (parent-owned storage) or a file-backed
    ``RemoteJournalAdapter`` in tests."""
    from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import (
        register_builtin_tools,
    )
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalBroker,
        ApprovalDecision,
        set_approval_broker,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
        ToolOrchestrator,
    )
    from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

    class _GrantBroker(ApprovalBroker):
        """The human already decided — answers any re-ask APPROVED so the
        replayed call passes every real gate (blacklist, write-path) with
        no second prompt; the kernel boundary is unchanged."""

        async def _ask(self, request: Any) -> Any:  # noqa: ANN001
            return ApprovalDecision.APPROVED

    registry = ToolRegistry()
    orchestrator = ToolOrchestrator()
    # Mirror the ORIGINAL turn's tool surface or qualified names resolve
    # differently on replay (audit W8-r3): `task` is the subagent dispatch
    # only when the manager flag was on, and approved MCP calls must find
    # the same qualified tool names the original agent registered.
    live_cfg: dict[str, Any] = {}
    try:
        from RxyCode.RxyCode1_1_0.config.settings import load_config

        live_cfg = load_config() or {}
    except Exception:
        live_cfg = {}
    subagents_on = False
    try:
        from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import (
            get_manager_or_none,
        )

        mgr = get_manager_or_none()
        if mgr is not None:
            subagents_on = bool(mgr.config.flags.subagents_enabled)
    except Exception:
        subagents_on = False
    register_builtin_tools(
        registry,
        orchestrator,
        rag_enabled=False,
        subagents_enabled=subagents_on,
        run_official_agent_enabled=bool(
            (live_cfg.get("execution") or {}).get(
                "run_official_agent_enabled", False
            )
        ),
    )
    mcp_clients: list[Any] = []
    raw_mcp = live_cfg.get("mcpServers")
    # Only inside a confined turn may we spawn MCP stdio servers — a bare
    # call (unit tests) must not reach out and start host processes.
    if (
        isinstance(raw_mcp, dict)
        and raw_mcp
        and os.environ.get("RXYCODE_TURN_RUN_ID", "").strip()
    ):
        try:
            from RxyCode.RxyCode1_1_0.mcp.client import load_mcp_servers

            loaded = await asyncio.to_thread(load_mcp_servers, raw_mcp)
            occupied = set(orchestrator.list_names())
            for name, mcp_tool in loaded.tools.items():
                if name in occupied:
                    continue
                metadata = getattr(mcp_tool, "metadata", None)
                risk = (
                    "danger"
                    if isinstance(metadata, dict)
                    and metadata.get("mcp_risk") == "danger"
                    else "write"
                )
                orchestrator.register(name, mcp_tool, risk=risk)
                occupied.add(name)
            mcp_clients = list(loaded.clients.values())
        except Exception:
            _LOG.warning("approved-resume: MCP server load failed", exc_info=True)
    tool = str(record.get("tool") or "")
    call_id = str(record.get("call_id") or "")
    attempt_id = str(record.get("attempt_id") or "")
    args = _approval_args(record)
    try:
        # At-most-once: reserve binds (attempt, call) BEFORE the side
        # effect — a duplicate resume observes 'reuse'/'uncertain' and
        # never re-runs.
        reservation = await asyncio.to_thread(
            journal.reserve,
            attempt_id=attempt_id,
            call_id=call_id,
            tool=tool,
            args=args,
        )
        if reservation.action == "reuse":
            stored = str(reservation.result or "")
            # The stored outcome decides — a completed call whose result
            # was an error marker is a FAILED call, not a successful
            # replay.
            return (not _tool_call_failed(stored)), stored
        if reservation.action != "execute":
            raise RuntimeError(
                f"resumed call {call_id} is journal-{reservation.action}; "
                "refusing a side effect"
            )
        cfg = {
            "safety": {
                # Without enabled=True the orchestrator bypasses blacklist,
                # write-path gate AND approval as `safety_disabled` — an
                # approved call must still pass every gate but the prompt.
                "enabled": True,
                "permission_mode": "confirm_all",
                "allowed_write_paths": _writable_domain(workdir),
            },
            "execution": {"workspace_root": str(workdir)},
        }
        set_approval_broker(_GrantBroker())
        try:
            output = await orchestrator.execute_tool(
                tool,
                args,
                cfg,
                call_id=call_id,
            )
        finally:
            set_approval_broker(None)
    finally:
        # MCP stdio servers are confined-child processes too — disconnect
        # every client so no server outlives the replayed call.
        for client in mcp_clients:
            try:
                client.disconnect()
            except Exception:
                pass
    # Completing is replay safety: whatever the orchestrator returned —
    # including an error marker — is now the durable outcome of THIS call.
    # A raise mid-side-effect instead leaves 'reserved' → recovery_required
    # on the next claim, never a blind second execution.
    text_out = str(output if output is not None else "")
    await asyncio.to_thread(
        journal.complete,
        attempt_id=attempt_id,
        call_id=call_id,
        tool=tool,
        args=args,
        result=text_out,
    )
    return (not _tool_call_failed(text_out)), text_out


async def run_sandboxed_turn() -> int:
    """The confined half of a drained run — entered when this module is
    executed with ``RXYCODE_TURN_RUN_ID`` set (inside the userns sandbox).

    The turn holds NO platform credentials: events, run reads, steer
    commands and durable approvals all travel the parent-owned control
    socket (``RXYCODE_CTL_SOCK``), and egress rides the parent's filtered
    CONNECT proxy over a private net namespace. A REAL ProtocolTui bound
    through bind_prompt_context remains the producer of tool/stream
    notifications (audit r3-F3). The result lands in
    ``.turn-result.json`` for the drain parent; the process always exits 0
    — errors live in the result file and the journaled events.
    """
    run_id = os.environ["RXYCODE_TURN_RUN_ID"].strip()
    ctl_sock = os.environ.get("RXYCODE_CTL_SOCK", "").strip()
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

    turn_error = ""
    cancelled_by_request = False
    paused_by_approval = False
    measured = {"tokens": 0}
    message = ""

    if not ctl_sock:
        # Fail closed: a confined turn without its control channel cannot
        # journal, read, or approve — running anyway would mean running
        # deaf (and is exactly what a credential-stripped fork looks like).
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": "failed",
                        "error": "confined turn started without RXYCODE_CTL_SOCK",
                        "tokens": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        return 0

    from rxycode_worker.agent_events import (
        bind_run,
        clear_web_run,
        remember_web_run,
    )
    from rxycode_worker.ctl import TurnChannel

    channel = TurnChannel(ctl_sock)

    # Private net namespace bring-up: lo down by default; the only door out
    # is the parent's filtered egress socket via a loopback relay.
    egress_relay = None
    net_sock = os.environ.get("RXYCODE_NET_SOCK", "").strip()
    egress_port = int(os.environ.get("RXYCODE_EGRESS_PORT", "0") or 0)
    if net_sock and egress_port:
        try:
            from rxycode_worker.netrelay import bring_up_loopback, start_relay

            bring_up_loopback()
            egress_relay = await start_relay(egress_port, net_sock)
        except Exception:
            _LOG.warning("run %s: egress relay start failed", run_id, exc_info=True)

    # Config lives in a parent-owned ro-bound dir; the writable data dir is
    # inside this workspace. The child copies config.yaml itself — the
    # parent NEVER writes into the workspace (a confined turn could plant a
    # destination symlink and make a later parent copy follow it onto host
    # files — audit r4-F2). This runs BEFORE the resume branch too: the
    # replayed call must resolve the same tool surface (MCP servers,
    # subagent flag) the original turn saw (audit W8-r4).
    config_src = os.environ.get("RXYCODE_TURN_CONFIG_SRC", "").strip()
    if config_src:
        try:
            src_cfg = Path(config_src) / "config.yaml"
            dst_dir = Path(os.environ.get("RXYCODE_DATA_DIR", str(workdir / ".data")))
            dst_dir.mkdir(parents=True, exist_ok=True)
            if src_cfg.is_file():
                dst = dst_dir / "config.yaml"
                shutil.copy2(src_cfg, dst)
                _merge_turn_config(dst, workdir)
        except OSError:
            _LOG.warning("run %s: config copy into workspace failed", run_id, exc_info=True)

    # Resume mode: a fresh confined process whose ONLY job is the stored,
    # approved call — no agent loop, no second decision.
    if os.environ.get("RXYCODE_TURN_RESUME", "").strip() == "1":
        return await _resume_turn(
            channel=channel,
            run_id=run_id,
            tenant_id=tenant_id,
            workdir=workdir,
            result_path=result_path,
        )

    emit = _RunEmit("", tenant_id, run_id, emitter=channel.emit)
    remember_web_run(
        "",
        tenant_id,
        run_id,
        parent_id=session_id,
        session_id=session_id,
        channel=channel,
    )

    try:
        loaded = await asyncio.to_thread(channel.load_run)
        message = str(loaded.get("message") or "")
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
            log — through the control channel, tagged with this attempt's
            lease epoch so retries accumulate instead of overwriting
            (audit r5-F4)."""
            while True:
                await asyncio.sleep(3.0)
                try:
                    inp = int(token_stats.input_tokens) - token0[0]
                    outp = int(token_stats.output_tokens) - token0[1]
                    if inp + outp <= 0:
                        continue
                    await asyncio.to_thread(
                        channel.emit,
                        "usage.delta",
                        {
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

        # Non-Full approvals ride the durable service through the parent:
        # request_approval persists the exact call, parks the run and
        # releases the lease; this process then unwinds via _RunPaused.
        # full_auto never reaches the broker (the orchestrator auto-allows).
        from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker

        set_approval_broker(
            _CtlApproval(channel, run_id=run_id, workdir=workdir).broker()
        )

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

        command_watcher = asyncio.create_task(
            _command_watchdog(
                lambda after: channel.commands(after_seq=after),
                run_id,
                main_task,
            )
        )
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
        except _RunPaused:
            # The durable ask is already persisted and the lease released
            # by the ctl op — this process's only remaining job is to say
            # so and die. Nothing else may write terminal state.
            paused_by_approval = True
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
        if (
            not turn_error
            and not paused_by_approval
            and agent_task.state != LifecycleState.DONE
        ):
            last = getattr(agent_task, "_last_error", None)
            if last is not None:
                turn_error = f"{type(last).__name__}: {last}"
            elif not cancelled_by_request:
                turn_error = f"agent ended in state {agent_task.state}"
    except _RunPaused:
        paused_by_approval = True
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
            if egress_relay is not None:
                egress_relay.close()
                await egress_relay.wait_closed()
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
                            "paused"
                            if paused_by_approval
                            else "cancelled"
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
    paused_run = False
    recovery = False
    resume_record: dict[str, Any] | None = None
    tokens = 0
    sandbox_id = ""
    provider = None
    workdir: Path | None = None
    proc: "asyncio.subprocess.Process | None" = None
    proc_identity: Any | None = None
    ctl_server: Any | None = None
    egress: Any | None = None
    # Per-claim dirs under state_root — removed at teardown so completed
    # runs cannot accumulate config copies, sockets or overlay layers
    # (audit W8-r6: retain=False means retain NOTHING).
    claim_dirs: list[Path] = []
    paused_evt = threading.Event()
    # The ctl op hands its approval_id back so the post-exit ``turn.paused``
    # marker names the exact ask this drain parked on (audit W8-r1).
    paused_info: dict[str, str] = {}
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
        claim_dirs.append(data_dir)
        # A stale result file from an earlier run in this workspace must
        # never be read as this run's outcome (audit r4-F3).
        (workdir / _TURN_RESULT).unlink(missing_ok=True)

        # Approval-resume journal: PARENT-OWNED, outside the sandbox's
        # writable workspace and never mounted — a wiped workdir can no
        # longer erase a reservation and win a second side effect (W8-r1).
        # Keyed by RUN so a later claim sees this claim's reservations —
        # keying by the fresh sandbox_id would recreate an empty journal
        # per claim and execute the same approved call twice (W8-r2).
        journal_dir = _run_journal_dir(provider.state_root, tenant_id, run_id)
        journal_dir.mkdir(parents=True, exist_ok=True)

        # Resume detection: the ONLY way a run leaves waiting_approval for a
        # claimable status is decide_approval(... approved) -> pending — so
        # a claimed run whose newest durable approval is approved replays
        # the stored call in a fresh confined child, not a fresh turn.
        # Resume cases that settle WITHOUT a child raise _ResumeSettled so
        # the verdict still flows through the shared finalize (metering
        # flush, terminal usage upsert, span close, quota release, notify)
        # — an early settle_run here would orphan the original turn's real
        # spend and skip the terminal hooks (audit W8-r3).
        try:
            resume_record = await asyncio.wait_for(
                asyncio.to_thread(
                    _pending_resume,
                    cfg.database_url,
                    tenant_id,
                    run_id,
                    state_root=provider.state_root,
                ),
                timeout=_LEASE_IO_BUDGET,
            )
        except Exception as exc:
            # An UNKNOWN handoff must stop execution, never restart the
            # original prompt beside a possibly-live namespace — that is
            # how doubled side effects are born (audit W8-r3).
            _LOG.warning("run %s: pending-resume probe failed", run_id, exc_info=True)
            raise _ResumeSettled(
                "recovery_required",
                f"pending-resume probe failed: {type(exc).__name__}: {exc}"[:1500],
            ) from exc
        if resume_record is not None and resume_record.get("teardown_unproven"):
            # The old claim's namespace could NOT be proven stopped —
            # replaying the approved call beside it risks a doubled side
            # effect. Fail closed: recovery_required, never a guess.
            try:
                await asyncio.to_thread(
                    append_event,
                    cfg.database_url,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type="approval.resumed",
                    payload={
                        "approval_id": str(
                            resume_record.get("approval_id") or ""
                        ),
                        "journal_state": "skipped",
                        "executed": False,
                        "reason": "teardown_unproven",
                    },
                )
            except Exception:
                _LOG.warning(
                    "run %s: approval.resumed emit failed", run_id, exc_info=True
                )
            raise _ResumeSettled(
                "recovery_required",
                "old claim's confined teardown could not be proven; "
                "refusing to replay beside an unproven namespace",
            )
        if resume_record is not None:
            from rxycode_worker.interrupt_resume import _journal_state

            before = await asyncio.to_thread(
                _journal_state,
                str(journal_dir),
                str(resume_record.get("attempt_id") or ""),
                str(resume_record.get("call_id") or ""),
            )
            if before in {"completed", "unknown"}:
                # The stored call already ran (or its outcome is
                # unrecoverable) — never execute twice; settle the claim.
                # For completed, success is the STORED result's verdict,
                # not the journal state alone: an error marker stored as
                # the result is a failed call (W8-r2).
                if before == "completed":
                    stored = await asyncio.to_thread(
                        _journal_result, journal_dir, resume_record
                    )
                    terminal = (
                        "failed" if _tool_call_failed(stored) else "succeeded"
                    )
                    detail = str(stored)[:400] if terminal == "failed" else ""
                else:
                    terminal = "recovery_required"
                    detail = (
                        f"resumed call "
                        f"{str(resume_record.get('call_id') or '')[:40]} "
                        "has journal state 'unknown'; its effect is "
                        "unprovable"
                    )
                try:
                    await asyncio.to_thread(
                        append_event,
                        cfg.database_url,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        event_type="approval.resumed",
                        payload={
                            "approval_id": str(
                                resume_record.get("approval_id") or ""
                            ),
                            "journal_state": before,
                            "executed": False,
                        },
                    )
                except Exception:
                    _LOG.warning(
                        "run %s: approval.resumed emit failed", run_id, exc_info=True
                    )
                raise _ResumeSettled(terminal, detail)

        # Drop the stale copied config — but only now, AFTER the resume
        # probe: a missing turn.paused marker already raised above, so a
        # possibly-live old child can never be racing this delete, and
        # the dir-fd path never follows a planted symlink to a host file
        # (audit W8-r5).
        _safe_unlink_inside(workdir / ".data", "config.yaml")

        # Task-private control dir (parent-owned, rw-bound at the same
        # path): the per-run ctl socket + the filtered egress socket. The
        # confined child reaches the control plane ONLY through ctl.sock.
        ctl_dir = provider.state_root / f"{sandbox_id}-ctl"
        ctl_dir.mkdir(parents=True, exist_ok=True)
        claim_dirs.append(ctl_dir)
        try:
            ctl_dir.chmod(0o700)
        except OSError:
            pass
        ctl_sock = ctl_dir / "ctl.sock"
        net_sock = ctl_dir / "net.sock"
        from rxycode_worker.ctl import CtlServer
        from rxycode_worker.egress import (
            EgressProxy,
            egress_allowlist_from_env,
            model_gateway_from_env,
        )

        ctl_server = CtlServer(
            ctl_sock,
            _ctl_handlers(
                cfg,
                tenant_id=tenant_id,
                run_id=run_id,
                epoch=epoch,
                workdir=workdir,
                journal_dir=journal_dir,
                paused=paused_evt,
                paused_info=paused_info,
                sandbox_id=sandbox_id,
            ),
        )
        await ctl_server.start()
        # The gateway holds the platform model key PARENT-SIDE: the child's
        # model entry is rewritten to 127.0.0.1:<port> by _merge_turn_config
        # and this proxy injects the real auth on the upstream hop.
        egress = EgressProxy(
            net_sock,
            egress_allowlist_from_env(),
            gateway=model_gateway_from_env(),
        )
        await egress.start()

        turn_env: dict[str, str] = {
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
            # Control channel + egress: the only two doors out of the
            # private mount/network namespace.
            "RXYCODE_CTL_SOCK": str(ctl_sock),
            "RXYCODE_NET_SOCK": str(net_sock),
            "RXYCODE_EGRESS_PORT": str(_EGRESS_PORT),
            # The child's model base_url — the loopback gateway. Anything
            # still reading RXYCODE_LLM_BASE_URL lands here honestly.
            "RXYCODE_LLM_BASE_URL": f"http://127.0.0.1:{_EGRESS_PORT}",
            # Every proxy-aware client (httpx, requests, pip, npm, curl,
            # git, Playwright) inherits these — the loopback relay bridges
            # to the parent's filtered CONNECT proxy.
            "HTTP_PROXY": f"http://127.0.0.1:{_EGRESS_PORT}",
            "HTTPS_PROXY": f"http://127.0.0.1:{_EGRESS_PORT}",
            "ALL_PROXY": f"http://127.0.0.1:{_EGRESS_PORT}",
            "http_proxy": f"http://127.0.0.1:{_EGRESS_PORT}",
            "https_proxy": f"http://127.0.0.1:{_EGRESS_PORT}",
            "all_proxy": f"http://127.0.0.1:{_EGRESS_PORT}",
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1",
        }
        # Task-private HOME + package caches under the workspace mount.
        turn_env.update(_task_turn_env(workdir))
        if resume_record is not None:
            turn_env["RXYCODE_TURN_RESUME"] = "1"
            turn_env["RXYCODE_TURN_APPROVAL"] = str(
                resume_record.get("approval_id") or ""
            )
        child_env = _child_env(turn_env)
        # The same module re-entered in turn mode — the sandbox sees the
        # system paths plus every code path this host actually uses
        # (container /repo, dev-host PYTHONPATH entries) read-only, and the
        # parent-controlled config dir read-only as RXYCODE_DATA_DIR.
        ro_binds = ["/repo", str(data_dir)] + [
            entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry
        ]
        # Task-private writable mounts: the control dir only — HOME and the
        # package caches live inside the workspace mount itself.
        rw_binds = [str(ctl_dir)]
        # System-package installs (apt/dpkg) write to a per-task PERSISTENT
        # overlay layer — never the host's /usr — when the kernel allows
        # userns overlayfs; otherwise the ro mounts honestly refuse. Upper
        # and work dirs live under the run's own state dir (same fs, as
        # --overlay requires) so installs survive across the task's turns.
        from rxycode_runner.sandbox.userns import overlay_dests

        overlays: list[tuple[str, str, str, str]] = []
        ovl_root = provider.state_root / f"{sandbox_id}-ovl"
        claim_dirs.append(ovl_root)
        # overlay_dests probes EVERY candidate with the real argv on the
        # real state-root fs — "direct" lowers use the system path; a
        # "seed" verdict (container /etc, Docker's injected file mounts)
        # gets a plain host copy as the lower so apt still gets a
        # private writable /etc (audit W8-r6); dests failing BOTH probe
        # shapes are skipped and stay honestly read-only.
        for root, kind in overlay_dests(provider.state_root).items():
            tag = root.strip("/") or "root"
            upper = ovl_root / f"{tag}-upper"
            work = ovl_root / f"{tag}-work"
            upper.mkdir(parents=True, exist_ok=True)
            work.mkdir(parents=True, exist_ok=True)
            lower = ""
            if kind == "seed":
                seed = ovl_root / f"{tag}-seed"
                if not seed.is_dir():
                    shutil.copytree(
                        root, seed, symlinks=True, dirs_exist_ok=True
                    )
                lower = str(seed)
            overlays.append((str(upper), str(work), root, lower))
        argv = provider.spawn_argv(
            sandbox_id,
            tenant_id=tenant_id,
            # ``python -m`` resolves sys.path[0] from the SPAWN cwd — a
            # writable project dir containing ``rxycode_worker/`` would
            # shadow this module and bypass approval/journal machinery
            # (audit W8-r7). chdir=/tmp (a private tmpfs mounted before
            # every bind — nothing can be pre-planted); the interpreter
            # flags live in _trusted_child_argv (audit W8-r8); the
            # child sets its real cwd itself via set_working_directory.
            argv=_trusted_child_argv(),
            env=child_env,
            ro_binds=ro_binds,
            rw_binds=rw_binds,
            overlays=overlays,
            chdir="/tmp",
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
        # Pin the child's (pid, create_time) NOW — later kill/sweep paths
        # must never act on a pid that was reaped and reassigned to an
        # unrelated process (audit W8-r3).
        try:
            import psutil

            proc_identity = psutil.Process(proc.pid)
        except Exception:
            proc_identity = None

        turn_task = asyncio.ensure_future(
            _wait_child(proc, stderr_tail, streamed, proc_identity)
        )
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
            elif status == "paused" or paused_evt.is_set():
                # The ctl op already parked the run (waiting_approval +
                # lease released); this drain's only job left is to step
                # away — never terminalize a parked run. paused_evt is the
                # fallback: a child killed between a successful ask and the
                # result-file write still counts as parked.
                paused_run = True
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

        if resume_record is not None and not paused_run and not lost_lease:
            # Resume truth is the durable journal, not the child's
            # self-report: the stored call "succeeded" only when the
            # journal marked it completed.
            from rxycode_worker.interrupt_resume import _journal_state

            try:
                after = await asyncio.to_thread(
                    _journal_state,
                    str(journal_dir),
                    str(resume_record.get("attempt_id") or ""),
                    str(resume_record.get("call_id") or ""),
                )
            except Exception:
                after = "unknown"
            try:
                await asyncio.to_thread(
                    append_event,
                    cfg.database_url,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type="approval.resumed",
                    payload={
                        "approval_id": str(resume_record.get("approval_id") or ""),
                        "call_id": str(resume_record.get("call_id") or ""),
                        "journal_state": after,
                        "executed": after == "completed",
                    },
                )
            except Exception:
                _LOG.warning(
                    "run %s: approval.resumed emit failed", run_id, exc_info=True
                )
            if after == "completed":
                # completed = replay safety, not success (W8-r2): read
                # the stored result and classify — an error marker the
                # call produced is a failed run, not a silent success.
                stored = await asyncio.to_thread(
                    _journal_result, journal_dir, resume_record
                )
                turn_error = stored[:400] if _tool_call_failed(stored) else ""
            elif not cancelled_by_request:
                if after == "unknown":
                    # The call may or may not have run — the journal cannot
                    # prove either way; label it recovery_required, not a
                    # clean failure (same contract resume_approved had).
                    recovery = True
                turn_error = (
                    f"resumed call {str(resume_record.get('call_id') or '')[:40]} "
                    f"did not complete (journal: {after})"
                )
    except _ResumeSettled as settled:
        # The resume verdict was decided above — express it through the
        # shared terminal machinery: "" is a clean success, a detail is a
        # failed run (plus run.error), recovery maps to
        # recovery_required. Usage/span/quota/notify still run below.
        turn_error = settled.detail if settled.status != "succeeded" else ""
        recovery = settled.status == "recovery_required"
    except LeaseRejected:
        lost_lease = True
    except Exception as exc:
        turn_error = f"{type(exc).__name__}: {exc}"
    finally:
        # A leftover confined child must not outlive the drain's decision.
        # proc_identity.is_running() re-verifies (pid, create_time) — a
        # reaped-and-reused pid is NOT ours to signal (audit W8-r3).
        if proc is not None and proc.returncode is None:
            try:
                if proc_identity is None or proc_identity.is_running():
                    proc.kill()
            except ProcessLookupError:
                pass
            except Exception:
                pass
        if ctl_server is not None:
            try:
                await ctl_server.stop()
            except Exception:
                pass
        if egress is not None:
            try:
                await egress.stop()
            except Exception:
                pass
        if provider is not None and sandbox_id:
            try:
                provider.destroy(sandbox_id, tenant_id=tenant_id)
            except Exception:
                pass
        # Per-claim dirs go last — the child is dead, the sockets are
        # closed and the record is destroyed; upper/work/seed layers and
        # the scrubbed config must not pile up under state_root
        # (audit W8-r6). run-keyed journal dir is deliberately kept.
        _remove_claim_dirs(claim_dirs)

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

    # A parked run is done FOR THIS CLAIM: request_approval already flipped
    # it to waiting_approval and released the lease — the watchdog's
    # LeaseRejected/lost_lease is expected fallout, not a lost claim, and
    # NO settle/finalize may run (the human decides next). The status read
    # is belt for a child killed in the pause-unwind window before writing
    # its result file.
    if paused_run or paused_evt.is_set():
        # Teardown marker: the confined child is already dead (waited
        # above) — this durable event is the proof a new claimant polls
        # for before replaying the approved call, so the old namespace
        # can never still be running beside the resume child (W8-r1).
        try:
            await asyncio.to_thread(
                append_event,
                cfg.database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type="turn.paused",
                payload={
                    "approval_id": str(paused_info.get("approval_id") or ""),
                    "worker_id": cfg.worker_id,
                    "epoch": int(epoch),
                },
            )
        except Exception:
            _LOG.warning(
                "run %s: turn.paused marker emit failed", run_id, exc_info=True
            )
        return True
    try:
        if (
            await asyncio.wait_for(
                asyncio.to_thread(run_status, cfg.database_url, run_id),
                timeout=_LEASE_IO_BUDGET,
            )
            == "waiting_approval"
        ):
            return True
    except Exception:
        pass

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
        # The run is about to terminalize without a proven ledger — park a
        # pending spool so a later drain pass converges it (the same
        # retention the cancel path uses; audit r16 propagation contract).
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
                "run %s: pending-usage spool write failed", run_id,
                exc_info=True,
            )
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
    terminal = (
        "succeeded"
        if not turn_error
        else "recovery_required"
        if recovery
        else "failed"
    )
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
