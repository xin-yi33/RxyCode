"""Submission-time model resolution for Web runs.

``resolve_run_model`` decides, BEFORE any run/session row is written,
which credential a run is bound to. The returned dict is the immutable
snapshot persisted on the run row and echoed (non-secret fields only) in
``run.created``. It never contains key material.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from rxycode_server.byok.crypto import BYOKUnavailable, load_keyring
from rxycode_server.persistence.models import ModelConnection, User, UserModel

PLATFORM_MODEL_REF = "platform"

def byok_enforced(mode: str | None = None) -> bool:
    """Web runs always require a user-owned BYOK model.

    ``mode`` and the legacy ``RXYCODE_BYOK_ENFORCE`` switch no longer grant
    access to the platform credential (product policy change, 2026-10-22).
    """
    del mode
    return True


def keyring_available() -> bool:
    try:
        load_keyring()
        return True
    except BYOKUnavailable:
        return False


def _model_snapshot(model: UserModel, connection: ModelConnection) -> dict:
    return {
        "model_ref": model.id,
        "model_id": model.model_id,
        "provider_id": connection.provider_id,
        "provider_name": connection.provider_name,
        "credential_source": "byok",
        "connection_id": connection.id,
        "credential_version": int(connection.credential_version or 0),
    }


def _resolve_owned_model(db: Session, record, model_ref: str) -> dict:
    model = db.get(UserModel, model_ref)
    if (
        model is None
        or model.tenant_id != record.tenant_id
        or model.owner_user_id != record.user_id
    ):
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    connection = db.get(ModelConnection, model.connection_id)
    if connection is None or connection.state != "active":
        raise HTTPException(status_code=409, detail="MODEL_UNAVAILABLE")
    if not connection.ciphertext:
        raise HTTPException(status_code=409, detail="MODEL_UNAVAILABLE")
    # The worker decrypts parent-side at claim time; check the keyring is
    # actually loadable now so a broken deploy fails submission, not runs.
    if not keyring_available():
        raise HTTPException(status_code=503, detail="BYOK_UNAVAILABLE")
    return _model_snapshot(model, connection)


def resolve_run_model(
    db: Session,
    record,
    model_ref: str | None,
    *,
    mode: str | None = None,
) -> dict | None:
    """Resolve the submitted/defaulted model_ref into a run snapshot.

    Web runs require a user-owned BYOK model — EXCEPT the narrow platform
    grant path: ``model_ref == "platform"`` resolves to the pinned
    platform snapshot ONLY when the caller owns an active grant row.
    Ownership is the durable platform_grants row; the legacy
    ``RXYCODE_PLATFORM_MODEL_USERS`` allowlist grants nothing.
    """
    requested = str(model_ref or "").strip()
    if requested == PLATFORM_MODEL_REF:
        from rxycode_server.platform_quota.service import (
            grant_for_user,
            platform_snapshot,
        )

        if grant_for_user(db, record.user_id) is None:
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
        return platform_snapshot()
    if requested:
        return _resolve_owned_model(db, record, requested)

    user = db.get(User, record.user_id)
    default_ref = str(user.default_model_ref or "") if user is not None else ""
    if default_ref == PLATFORM_MODEL_REF:
        # Defaulted to the platform model — same grant check as an
        # explicit ref; a stale default does not resurrect access.
        from rxycode_server.platform_quota.service import (
            grant_for_user,
            platform_snapshot,
        )

        if grant_for_user(db, record.user_id) is not None:
            return platform_snapshot()
    elif default_ref:
        model = db.get(UserModel, default_ref)
        if (
            model is not None
            and model.tenant_id == record.tenant_id
            and model.owner_user_id == record.user_id
        ):
            return _resolve_owned_model(db, record, default_ref)
    # Nothing explicit and no usable BYOK default: the grant holder's
    # implicit model IS the platform grant — the free tier's first-send
    # path. Non-holders keep the honest BYOK_REQUIRED refusal.
    from rxycode_server.platform_quota.service import (
        grant_for_user,
        platform_snapshot,
    )

    if grant_for_user(db, record.user_id) is not None:
        return platform_snapshot()
    raise HTTPException(status_code=403, detail="BYOK_REQUIRED")
