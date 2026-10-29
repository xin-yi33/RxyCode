"""Grant lifecycle for the platform-funded free quota.

Model pin: the platform credential serves exactly ``PLATFORM_MODEL_ID``
and nothing else — the resolver snapshot, the catalog item, the worker
gateway, and this module's admission path all name that one model id.

Counter discipline:

* Claim (registration / backfill): ``UPDATE ... WHERE user_id IS NULL``
  under ``FOR UPDATE SKIP LOCKED`` — concurrent registrations can never
  exceed the seeded slot count and never double-assign a slot.
* Admission (create_run): under the per-user advisory lock the gate
  already holds, the grant row is taken ``FOR UPDATE``, ``tokens_used <
  token_cap`` is re-checked, and a second ACTIVE platform run for the
  same user is refused — two concurrent platform runs can never both
  pass a near-cap check.
* Settle (worker finalize): the run's real metered total is folded into
  ``tokens_used`` by ``LEAST(tokens_used + delta, token_cap)`` while the
  grant row is locked; a ``platform.settled`` run event makes the write
  idempotent across lease-loss re-finalization.

Overshoot bound: the durable counter can NEVER exceed ``token_cap``.
A single in-flight run may spend slightly past the grant's remaining
tokens before the watchdog cuts it (metering granularity of the
stderr usage heartbeat) — the CLAMP only bounds what is *accounted*,
the watchdog bounds what is *spent*. Both bounds are documented on the
run's ledger via the ``platform.settled`` marker.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import (
    PlatformGrant,
    Run,
    RunEvent,
    User,
)

_LOG = logging.getLogger(__name__)

#: The one model the platform credential will ever serve.
PLATFORM_MODEL_ID = "deepseek-v4.1-flash"
#: ``model_ref`` value clients submit to select the platform model.
PLATFORM_MODEL_REF = "platform"
PLATFORM_PROVIDER_ID = "opencode-go"
PLATFORM_PROVIDER_NAME = "OpenCode Go"
PLATFORM_DISPLAY_NAME = "平台赠送 · DeepSeek Flash"
PLATFORM_TOKEN_CAP = 10_000_000
PLATFORM_SLOT_COUNT = 10
#: Human-readable refusal for an exhausted grant (also the frontend's
#: QUOTA_REASON_TEXT["platform_quota"] copy — keep them identical).
PLATFORM_EXHAUSTED_TEXT = "平台赠送额度已用完"

_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"


def env_api_key() -> str:
    """The platform credential — parent-side worker env only.

    This value is never passed to the confined child, never written to
    the child config, events, logs, or any API response."""
    return os.environ.get("RXYCODE_PLATFORM_API_KEY", "").strip()


def env_base_url() -> str:
    """OpenCode Go upstream. Operator-overridable; defaults to the
    deployment's documented endpoint."""
    return os.environ.get("RXYCODE_PLATFORM_BASE_URL", "").strip() or _DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Lookup helpers


def grant_for_user(db: Session, user_id: str) -> PlatformGrant | None:
    """The user's active grant, or None — never a 403-style leak."""
    if not user_id:
        return None
    return db.scalars(
        select(PlatformGrant).where(
            PlatformGrant.user_id == user_id,
            PlatformGrant.status == "active",
        )
    ).one_or_none()


def grant_active(database_url: str, user_id: str) -> bool:
    """Worker-parent re-check at claim time: an ACTIVE grant bound to the
    approved model still covers this actor. One indexed lookup; the drain
    calls it only for platform-snapshotted runs."""
    if not user_id:
        return False
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            return (
                db.scalars(
                    select(PlatformGrant.id).where(
                        PlatformGrant.user_id == user_id,
                        PlatformGrant.status == "active",
                        PlatformGrant.model_id == PLATFORM_MODEL_ID,
                    )
                ).first()
                is not None
            )
    finally:
        engine.dispose()


def remaining(grant: PlatformGrant | None) -> int:
    if grant is None:
        return 0
    return max(0, int(grant.token_cap or 0) - int(grant.tokens_used or 0))


def quota_json(grant: PlatformGrant) -> dict[str, int]:
    cap = int(grant.token_cap or 0)
    used = int(grant.tokens_used or 0)
    return {
        "token_cap": cap,
        "tokens_used": used,
        "tokens_remaining": max(0, cap - used),
    }


def platform_catalog_item(grant: PlatformGrant) -> dict[str, Any]:
    """The per-user catalog row — emitted ONLY for grant holders."""
    left = remaining(grant)
    return {
        "model_ref": PLATFORM_MODEL_REF,
        "model_id": PLATFORM_MODEL_ID,
        "display_name": PLATFORM_DISPLAY_NAME,
        "provider_id": PLATFORM_PROVIDER_ID,
        "provider_name": PLATFORM_PROVIDER_NAME,
        "connection_id": "",
        "connection_name": PLATFORM_PROVIDER_NAME,
        "source": "platform",
        "status": "available" if left > 0 else "exhausted",
        "input_capabilities": {
            "text": True,
            "images": False,
            "files": True,
            "verified": False,
        },
        "quota": quota_json(grant),
    }


def platform_snapshot() -> dict[str, Any]:
    """The immutable run-snapshot for a platform-credential run.

    Carries identifiers only — the actual key lives in the worker's
    environment and is bound at claim time by ``_resolve_run_gateway``.
    """
    return {
        "model_ref": PLATFORM_MODEL_REF,
        "model_id": PLATFORM_MODEL_ID,
        "provider_id": PLATFORM_PROVIDER_ID,
        "provider_name": PLATFORM_PROVIDER_NAME,
        "credential_source": "platform",
        "connection_id": "",
        "credential_version": 0,
    }


# ---------------------------------------------------------------------------
# Slot claim (registration + backfill)


def claim_slot(db: Session, *, user_id: str, tenant_id: str) -> PlatformGrant | None:
    """Atomically claim the lowest unclaimed slot for ``user_id``.

    ``FOR UPDATE SKIP LOCKED`` + the conditional ``user_id IS NULL``
    update make double-claims impossible: a concurrent registrar either
    picks a different row or updates zero rows and moves on. Returns the
    claimed grant, the user's existing grant (idempotent), or None when
    all slots are taken.
    """
    existing = grant_for_user(db, user_id)
    if existing is not None:
        return existing
    row = db.scalars(
        select(PlatformGrant)
        .where(PlatformGrant.user_id.is_(None))
        .order_by(PlatformGrant.slot_no)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            updated = db.execute(
                text(
                    "UPDATE platform_grants SET user_id = :u, "
                    "tenant_id = :t, claimed_at = :now "
                    "WHERE id = :id AND user_id IS NULL"
                ),
                {"u": user_id, "t": tenant_id, "now": now, "id": row.id},
            )
            if int(updated.rowcount or 0) != 1:
                # Lost the race for this slot — the caller's retry picks
                # the next open row, or reports no slot.
                return None
    except IntegrityError:
        # A racing claim for the SAME user committed first and the
        # partial unique index stopped this write. The savepoint keeps
        # the caller's transaction (e.g. the registration INSERT) alive;
        # the winner's grant is now visible — return it, idempotent.
        return grant_for_user(db, user_id)
    db.flush()
    db.refresh(row)
    return row


def slot_state(db: Session) -> dict[str, Any]:
    """Operator-facing summary: claimed user ids + open slot count."""
    rows = db.scalars(select(PlatformGrant).order_by(PlatformGrant.slot_no)).all()
    claimed = [
        {"slot_no": int(row.slot_no), "user_id": str(row.user_id)} for row in rows if row.user_id
    ]
    return {
        "slots": int(len(rows)),
        "claimed": claimed,
        "open": int(len(rows)) - len(claimed),
    }


# ---------------------------------------------------------------------------
# Admission (create_run transaction)


class PlatformQuotaRefused(Exception):
    """A platform-grant admission refusal with a stable machine code.

    The API layer maps codes: ``PLATFORM_NOT_ALLOWED`` -> 404
    MODEL_NOT_FOUND (same as an unknown ref — no existence leak),
    ``PLATFORM_QUOTA_EXHAUSTED`` -> 429 ``platform_quota``,
    ``PLATFORM_RUN_ACTIVE`` -> 429 ``concurrency``.
    """

    def __init__(self, code: str, detail: str, *, limit: int = 0) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.limit = limit


_ACTIVE_RUN_STATUSES = (
    "pending",
    "running",
    "leased",
    "cancel_requested",
    "waiting_approval",
)


def check_admission(db: Session, *, tenant_id: str, user_id: str) -> PlatformGrant:
    """Serialize and admit one platform run inside the caller's transaction.

    The caller already holds the per-user advisory lock (gate.reserve);
    locking the grant row ``FOR UPDATE`` here makes the
    ``tokens_used < token_cap`` check race-free against a settling
    worker, and the active-run scan under the same lock makes two
    concurrent platform runs impossible (a stale second submission sees
    the first run already committed).
    """
    grant = db.scalars(
        select(PlatformGrant)
        .where(
            PlatformGrant.user_id == user_id,
            PlatformGrant.status == "active",
        )
        .with_for_update()
    ).one_or_none()
    if grant is None:
        raise PlatformQuotaRefused(
            "PLATFORM_NOT_ALLOWED", "platform model is not granted to this user"
        )
    if grant.model_id != PLATFORM_MODEL_ID:
        raise PlatformQuotaRefused(
            "PLATFORM_NOT_ALLOWED", "platform grant is bound to another model"
        )
    if int(grant.tokens_used or 0) >= int(grant.token_cap or 0):
        raise PlatformQuotaRefused(
            "PLATFORM_QUOTA_EXHAUSTED",
            PLATFORM_EXHAUSTED_TEXT,
            limit=int(grant.token_cap or 0),
        )
    active = db.execute(
        select(func.count())
        .select_from(Run)
        .join(RunEvent, (RunEvent.run_id == Run.id) & (RunEvent.seq == 1))
        .where(
            Run.tenant_id == tenant_id,
            Run.credential_source == "platform",
            Run.status.in_(_ACTIVE_RUN_STATUSES),
            RunEvent.type == "run.created",
            RunEvent.payload["quota"]["user_id"].astext == user_id,
        )
    ).scalar()
    if int(active or 0) > 0:
        raise PlatformQuotaRefused("PLATFORM_RUN_ACTIVE", "平台赠送任务正在运行，请等待完成后再试")
    return grant


# ---------------------------------------------------------------------------
# Settlement (worker finalize)


def _settled_total(db: Session, run_id: str) -> int:
    """Metered tokens already folded into the grant for this run."""
    value = db.scalar(
        select(func.coalesce(func.max(text("(payload->>'applied_total')::bigint")), 0)).where(
            RunEvent.run_id == run_id,
            RunEvent.type == "platform.settled",
        )
    )
    return int(value or 0)


def grant_overrun(
    database_url: str,
    *,
    user_id: str,
    run_id: str,
    metered: int,
) -> bool:
    """The worker watchdog's overshoot probe: True when the grant's
    durable counter plus this run's UNCHARGED metered spend reaches the
    cap — the run is cancelled within one metering poll. ``metered`` is
    the caller's fresh across-attempt total; spend already folded into
    the counter (``platform.settled`` markers) is subtracted so a
    re-finalized attempt never double-counts.
    """
    if not user_id:
        return False
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            grant = grant_for_user(db, user_id)
            if grant is None:
                return False
            applied = _settled_total(db, run_id)
            uncharged = max(0, int(metered or 0) - applied)
            return int(grant.tokens_used or 0) + uncharged >= int(grant.token_cap or 0)
    finally:
        engine.dispose()


def settle_grant(
    database_url: str,
    *,
    tenant_id: str,
    user_id: str,
    run_id: str,
    tokens: int,
) -> int | None:
    """Fold this run's real spend into the durable grant counter.

    Locks run + grant in the canonical order (run first — every event
    writer serializes on it), computes ``delta = total - already_applied``
    from the ``platform.settled`` marker so a re-finalized run charges
    only new spend, then applies ``LEAST(tokens_used + delta, cap)``.
    Returns the post-settle ``tokens_used`` or None when the grant is
    gone — a revoked grant still records spend on its own row.
    """
    total = max(0, int(tokens or 0))
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                return None
            grant = db.scalars(
                select(PlatformGrant)
                .where(
                    PlatformGrant.user_id == user_id,
                    PlatformGrant.status == "active",
                )
                .with_for_update()
            ).one_or_none()
            if grant is None:
                return None
            applied = _settled_total(db, run_id)
            delta = max(0, total - applied)
            if delta > 0:
                db.execute(
                    text(
                        "UPDATE platform_grants SET tokens_used = "
                        "LEAST(tokens_used + :delta, token_cap) "
                        "WHERE id = :gid AND tokens_used < token_cap"
                    ),
                    {"delta": delta, "gid": grant.id},
                )
                db.flush()
                db.refresh(grant)
            # The marker is durable with the counter update in ONE commit:
            # a lease-lost re-finalize recomputes the same cumulative total
            # and applies only the residue — never the same spend twice.
            from rxycode_server.events.store import append_event_in

            append_event_in(
                db,
                run,
                "platform.settled",
                {
                    "applied_total": total,
                    "delta": delta,
                    "tokens_used": int(grant.tokens_used or 0),
                    "token_cap": int(grant.token_cap or 0),
                    "grant_id": str(grant.id),
                    "model_id": PLATFORM_MODEL_ID,
                },
            )
            db.commit()
            return int(grant.tokens_used or 0)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Backfill (scripts/platform_slots.py)


def backfill_grants(db: Session) -> dict[str, Any]:
    """Claim open slots for existing users in ``created_at`` order.

    Idempotent: granted users are skipped, an empty slot list is a no-op,
    and each claim uses the same SKIP LOCKED path as registration. Only
    user ids leave this function — never emails.
    """
    from rxycode_server.persistence.models import Membership

    users = db.scalars(select(User).order_by(User.created_at.asc().nulls_last(), User.id)).all()
    tenants = dict(db.execute(select(Membership.user_id, Membership.tenant_id)).all())
    granted_now: list[dict[str, Any]] = []
    for user in users:
        if grant_for_user(db, user.id) is not None:
            continue
        claimed = claim_slot(
            db,
            user_id=user.id,
            tenant_id=str(tenants.get(user.id) or ""),
        )
        if claimed is None:
            break
        granted_now.append({"slot_no": int(claimed.slot_no), "user_id": str(user.id)})
    db.commit()
    state = slot_state(db)
    return {"granted_now": granted_now, **state}
