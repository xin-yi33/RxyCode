"""Submission-time model resolution for Web runs.

``resolve_run_model`` decides, BEFORE any run/session row is written,
which credential a run is bound to. The returned dict is the immutable
snapshot persisted on the run row and echoed (non-secret fields only) in
``run.created``. It never contains key material.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from sqlalchemy.orm import Session

from rxycode_server.byok.crypto import BYOKUnavailable, load_keyring
from rxycode_server.persistence.models import ModelConnection, User, UserModel

PLATFORM_MODEL_REF = "platform"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def byok_enforced(mode: str | None = None) -> bool:
    """``RXYCODE_BYOK_ENFORCE`` wins; unset → on in cloud mode, off locally."""
    raw = os.environ.get("RXYCODE_BYOK_ENFORCE", "").strip().lower()
    if raw:
        return raw in _TRUE
    return mode == "cloud"


def platform_model_users() -> frozenset[str]:
    """Immutable allowlist of user ids allowed to ride the platform key."""
    return frozenset(
        part.strip()
        for part in os.environ.get("RXYCODE_PLATFORM_MODEL_USERS", "").split(",")
        if part.strip()
    )


def platform_model_name() -> str:
    """Display name for the deployed model — never the credential."""
    return os.environ.get("RXYCODE_LLM_MODEL", "").strip() or "deployed"


def keyring_available() -> bool:
    try:
        load_keyring()
        return True
    except BYOKUnavailable:
        return False


def _platform_snapshot() -> dict:
    return {
        "model_ref": PLATFORM_MODEL_REF,
        "model_id": platform_model_name(),
        "provider_id": "platform",
        "provider_name": "平台额度",
        "credential_source": "platform",
        "connection_id": "",
        "credential_version": 0,
    }


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

    Returns None only when enforcement is off and nothing was selected —
    the legacy env-gateway path. Otherwise raises a stable-code
    HTTPException or returns the snapshot dict.
    """
    requested = str(model_ref or "").strip()
    allowed = platform_model_users()
    if requested == PLATFORM_MODEL_REF:
        if record.user_id not in allowed:
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
        return _platform_snapshot()
    if requested:
        return _resolve_owned_model(db, record, requested)

    user = db.get(User, record.user_id)
    default_ref = str(user.default_model_ref or "") if user is not None else ""
    if default_ref:
        model = db.get(UserModel, default_ref)
        if (
            model is not None
            and model.tenant_id == record.tenant_id
            and model.owner_user_id == record.user_id
        ):
            return _resolve_owned_model(db, record, default_ref)
    if record.user_id in allowed:
        return _platform_snapshot()
    if byok_enforced(mode):
        raise HTTPException(status_code=403, detail="BYOK_REQUIRED")
    return None
