"""BYOK model connections + the per-user model catalogue (PRD §7.2).

Every endpoint is authenticated; every read/write filters on BOTH
tenant_id and owner_user_id — a foreign connection or model is a 404,
never a 403 that would leak existence. Key material is sealed with
AES-256-GCM (byok.crypto) before it touches the database and is never
returned, logged, or echoed — not even masked.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.byok.crypto import (
    BYOKDecryptError,
    BYOKUnavailable,
    connection_aad,
    decrypt,
    encrypt,
)
from rxycode_server.byok.netguard import vet_base_url
from rxycode_server.byok.resolver import (
    PLATFORM_MODEL_REF,
    byok_enforced,
    keyring_available,
    platform_model_name,
    platform_model_users,
)
from rxycode_server.persistence.models import ModelConnection, User, UserModel

router = APIRouter()

_MAX_KEY_LEN = 512
_MAX_MODEL_ID_LEN = 256
_MAX_MODEL_IDS = 100


def _model_manager():
    """Shared provider presets/discovery/probe — the CLI's model manager,
    lazily imported so the web surface never forks the provider registry."""
    try:
        from RxyCode.RxyCode1_1_0.config import model_manager
    except ImportError:
        from config import model_manager
    return model_manager


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _conn_json(row: ModelConnection, model_count: int = 0) -> dict:
    """Public shape — has_key is a boolean, never the key, never a mask."""
    tested_at = _aware(row.tested_at)
    updated_at = _aware(row.updated_at)
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "provider_name": row.provider_name,
        "display_name": row.display_name,
        "base_url": row.base_url,
        "api_transport": row.api_transport,
        "has_key": bool(row.ciphertext),
        "credential_version": int(row.credential_version or 0),
        "state": row.state,
        "test_status": row.test_status,
        "test_error": row.test_error,
        "tested_at": tested_at.isoformat() if tested_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "model_count": model_count,
    }


def _model_json(model: UserModel, connection: ModelConnection | None) -> dict:
    status = "available"
    if connection is None or connection.state != "active":
        status = "revoked"
    elif not connection.ciphertext:
        status = "no_key"
    return {
        "model_ref": model.id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "provider_id": connection.provider_id if connection else "",
        "provider_name": connection.provider_name if connection else "",
        "connection_id": model.connection_id,
        "connection_name": connection.display_name if connection else "",
        "source": "byok",
        "status": status,
    }


def _owned_connection(db: Session, record, connection_id: str) -> ModelConnection:
    row = db.get(ModelConnection, connection_id)
    if (
        row is None
        or row.tenant_id != record.tenant_id
        or row.owner_user_id != record.user_id
    ):
        raise HTTPException(status_code=404, detail="CONNECTION_NOT_FOUND")
    return row


def _owned_model(db: Session, record, model_ref: str) -> UserModel:
    row = db.get(UserModel, model_ref)
    if (
        row is None
        or row.tenant_id != record.tenant_id
        or row.owner_user_id != record.user_id
    ):
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    return row


def _decrypt_connection(conn: ModelConnection, record) -> str:
    """Open the stored credential under its current version AAD."""
    if conn.state != "active" or not conn.ciphertext or not conn.nonce:
        raise HTTPException(status_code=409, detail="MODEL_UNAVAILABLE")
    try:
        return decrypt(
            conn.ciphertext,
            conn.nonce,
            str(conn.key_id or ""),
            aad=connection_aad(
                tenant_id=record.tenant_id,
                owner_user_id=record.user_id,
                connection_id=conn.id,
                credential_version=int(conn.credential_version or 0),
            ),
        )
    except BYOKUnavailable:
        raise HTTPException(status_code=503, detail="BYOK_UNAVAILABLE") from None
    except BYOKDecryptError:
        raise HTTPException(status_code=409, detail="MODEL_UNAVAILABLE") from None


def _redact(text: object, secret: str) -> str:
    value = str(text or "")
    if secret:
        value = value.replace(secret, "[REDACTED]")
    return value[:256]


def _valid_model_id(raw: str) -> str | None:
    """model_manager has no reusable pure validator — model ids there are
    validated implicitly by probe/persist. Web-side rule: stripped, 1..256
    chars, no whitespace or control characters."""
    mid = str(raw or "").strip()
    if not mid or len(mid) > _MAX_MODEL_ID_LEN:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in mid):
        return None
    return mid


def _clear_default_if_removed(db: Session, user: User | None, removed_refs: list[str]) -> None:
    if user is not None and (user.default_model_ref or "") in removed_refs:
        user.default_model_ref = None


class _ConnectionIn(BaseModel):
    preset_id: str | None = None
    provider_name: str | None = None
    base_url: str | None = None
    display_name: str | None = None
    api_key: str = ""


class _ConnectionPatch(BaseModel):
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class _ModelsIn(BaseModel):
    model_ids: list[str]


class _TestIn(BaseModel):
    model_id: str | None = None
    allow_billable: bool = False


class _DefaultIn(BaseModel):
    model_ref: str | None = None


@router.get("/api/v1/models/providers")
def list_providers(request: Request) -> dict:
    current_record(request)
    return {"providers": _model_manager().list_provider_presets()}


@router.get("/api/v1/models/access")
def model_access(
    request: Request, db: Session = Depends(db_session)
) -> dict:
    record = current_record(request)
    user = db.get(User, record.user_id)
    return {
        "require_byok": byok_enforced(getattr(request.app.state, "mode", None)),
        "platform_allowed": record.user_id in platform_model_users(),
        "byok_available": keyring_available(),
        "default_model_ref": (user.default_model_ref if user else None) or None,
    }


@router.get("/api/v1/model-connections")
def list_connections(
    request: Request, db: Session = Depends(db_session)
) -> dict:
    record = current_record(request)
    rows = db.scalars(
        select(ModelConnection).where(
            ModelConnection.tenant_id == record.tenant_id,
            ModelConnection.owner_user_id == record.user_id,
        )
    ).all()
    counts = dict(
        db.execute(
            select(UserModel.connection_id, func.count())
            .where(
                UserModel.tenant_id == record.tenant_id,
                UserModel.owner_user_id == record.user_id,
            )
            .group_by(UserModel.connection_id)
        ).all()
    )
    return {
        "connections": [
            _conn_json(row, int(counts.get(row.id, 0))) for row in rows
        ]
    }


@router.post("/api/v1/model-connections", status_code=201)
def create_connection(
    payload: _ConnectionIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    mm = _model_manager()
    preset_id = (payload.preset_id or "").strip()
    base_url = (payload.base_url or "").strip()
    provider_name = (payload.provider_name or "").strip()
    if preset_id:
        preset = next(
            (p for p in mm.list_provider_presets() if p.get("id") == preset_id), None
        )
        if preset is None:
            raise HTTPException(status_code=400, detail="INVALID_INPUT")
        base_url = str(preset.get("base_url") or "")
        provider_id = str(preset.get("id") or "")
        provider_name = str(preset.get("name") or provider_name)
    else:
        if not base_url:
            raise HTTPException(status_code=400, detail="INVALID_BASE_URL")
        try:
            base_url = vet_base_url(base_url)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_BASE_URL") from None
        meta = mm.resolve_provider_meta(base_url, provider_name=provider_name)
        provider_id = str(meta.get("id") or "")
        provider_name = str(meta.get("name") or "")
    api_key = payload.api_key.strip()
    if not api_key or len(api_key) > _MAX_KEY_LEN:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    display_name = (payload.display_name or "").strip()[:128] or provider_name

    connection_id = "mc_" + uuid.uuid4().hex
    credential_version = 1
    try:
        ciphertext, nonce, key_id = encrypt(
            api_key,
            aad=connection_aad(
                tenant_id=record.tenant_id,
                owner_user_id=record.user_id,
                connection_id=connection_id,
                credential_version=credential_version,
            ),
        )
    except BYOKUnavailable:
        # Nothing is written — a half-created connection holding a key we
        # could not seal would be worse than refusing.
        raise HTTPException(status_code=503, detail="BYOK_UNAVAILABLE") from None
    row = ModelConnection(
        id=connection_id,
        tenant_id=record.tenant_id,
        owner_user_id=record.user_id,
        provider_id=provider_id[:64],
        provider_name=provider_name[:128],
        display_name=display_name,
        base_url=base_url[:512],
        ciphertext=ciphertext,
        nonce=nonce,
        key_id=key_id,
        encryption_version=1,
        credential_version=credential_version,
        state="active",
        test_status="untested",
    )
    db.add(row)
    db.commit()
    return {"connection": _conn_json(row)}


@router.patch("/api/v1/model-connections/{connection_id}")
def patch_connection(
    connection_id: str,
    payload: _ConnectionPatch,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)

    if payload.display_name is not None:
        conn.display_name = payload.display_name.strip()[:128]
    new_base_url = (payload.base_url or "").strip()
    base_url_changed = False
    if new_base_url:
        try:
            vetted = vet_base_url(new_base_url)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_BASE_URL") from None
        base_url_changed = vetted != conn.base_url
        if base_url_changed:
            conn.base_url = vetted
    new_key = (payload.api_key or "").strip()
    if payload.api_key is not None and new_key and len(new_key) > _MAX_KEY_LEN:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")

    if new_key or base_url_changed:
        # AAD binds (connection, credential_version): bump the version and
        # re-seal — the old snapshot AADs still verify for in-flight runs.
        old_version = int(conn.credential_version or 0)
        plaintext = new_key
        if not plaintext and conn.ciphertext:
            try:
                plaintext = decrypt(
                    conn.ciphertext,
                    conn.nonce,
                    str(conn.key_id or ""),
                    aad=connection_aad(
                        tenant_id=record.tenant_id,
                        owner_user_id=record.user_id,
                        connection_id=conn.id,
                        credential_version=old_version,
                    ),
                )
            except BYOKUnavailable:
                raise HTTPException(
                    status_code=503, detail="BYOK_UNAVAILABLE"
                ) from None
            except BYOKDecryptError:
                raise HTTPException(
                    status_code=409, detail="MODEL_UNAVAILABLE"
                ) from None
        conn.credential_version = old_version + 1
        if plaintext:
            try:
                ciphertext, nonce, key_id = encrypt(
                    plaintext,
                    aad=connection_aad(
                        tenant_id=record.tenant_id,
                        owner_user_id=record.user_id,
                        connection_id=conn.id,
                        credential_version=conn.credential_version,
                    ),
                )
            except BYOKUnavailable:
                raise HTTPException(
                    status_code=503, detail="BYOK_UNAVAILABLE"
                ) from None
            conn.ciphertext = ciphertext
            conn.nonce = nonce
            conn.key_id = key_id
        conn.test_status = "untested"
        conn.test_error = None
        conn.tested_at = None
    conn.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"connection": _conn_json(conn)}


@router.post("/api/v1/model-connections/{connection_id}/clear-key")
def clear_connection_key(
    connection_id: str,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)
    conn.ciphertext = None
    conn.nonce = None
    conn.key_id = None
    conn.credential_version = int(conn.credential_version or 0) + 1
    conn.test_status = "untested"
    conn.test_error = None
    conn.tested_at = None
    conn.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"connection": _conn_json(conn)}


@router.delete("/api/v1/model-connections/{connection_id}")
def delete_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)
    removed_refs = [
        str(mid)
        for mid in db.scalars(
            select(UserModel.id).where(UserModel.connection_id == conn.id)
        ).all()
    ]
    _clear_default_if_removed(db, db.get(User, record.user_id), removed_refs)
    db.delete(conn)
    db.commit()
    return {"deleted": True}


@router.post("/api/v1/model-connections/{connection_id}/discover")
def discover_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)
    api_key = _decrypt_connection(conn, record)
    try:
        base_url = vet_base_url(conn.base_url)
    except ValueError:
        return {
            "success": False,
            "models": [],
            "error": "base_url failed vetting",
            "error_code": "invalid_base_url",
        }
    result = _model_manager().discover_provider_models(
        api_key=api_key, base_url=base_url
    )
    known = {
        str(mid)
        for mid in db.scalars(
            select(UserModel.model_id).where(
                UserModel.connection_id == conn.id
            )
        ).all()
    }
    models = [
        {**model, "added": str(model.get("id") or "") in known}
        for model in (result.get("models") or [])
        if isinstance(model, dict)
    ]
    return {
        "success": bool(result.get("success")),
        "models": models,
        "error": _redact(result.get("error") or "", api_key),
        "error_code": str(result.get("error_code") or ""),
        "elapsed": result.get("elapsed"),
    }


@router.post("/api/v1/model-connections/{connection_id}/models")
def add_models(
    connection_id: str,
    payload: _ModelsIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)
    if len(payload.model_ids or []) > _MAX_MODEL_IDS:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    model_ids = list(payload.model_ids or [])
    existing = {
        str(mid): str(ref)
        for mid, ref in db.execute(
            select(UserModel.model_id, UserModel.id).where(
                UserModel.connection_id == conn.id
            )
        ).all()
    }
    results = []
    seen: set[str] = set()
    for raw in model_ids:
        mid = _valid_model_id(raw)
        if mid is None:
            results.append(
                {"model_id": str(raw or "")[:64], "status": "invalid"}
            )
            continue
        if mid in existing or mid in seen:
            results.append(
                {
                    "model_id": mid,
                    "status": "exists",
                    "model_ref": existing.get(mid),
                }
            )
            continue
        row = UserModel(
            id="m_" + uuid.uuid4().hex,
            tenant_id=record.tenant_id,
            owner_user_id=record.user_id,
            connection_id=conn.id,
            model_id=mid,
            display_name=mid,
        )
        db.add(row)
        db.flush()
        existing[mid] = row.id
        seen.add(mid)
        results.append(
            {"model_id": mid, "status": "added", "model_ref": row.id}
        )
    db.commit()
    return {"results": results}


@router.post("/api/v1/model-connections/{connection_id}/test")
def test_connection(
    connection_id: str,
    payload: _TestIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    conn = _owned_connection(db, record, connection_id)
    model_id = (payload.model_id or "").strip()
    if model_id and not payload.allow_billable:
        # A chat probe costs real tokens on the user's own key — it must
        # never fire on a bare click.
        raise HTTPException(status_code=400, detail="BILLABLE_TEST_NOT_CONFIRMED")
    api_key = _decrypt_connection(conn, record)
    mm = _model_manager()
    if model_id:
        result = mm.probe_model_connection(
            api_key=api_key, base_url=conn.base_url, provider_model_id=model_id
        )
    else:
        # Free check: the provider's GET /models catalogue only.
        result = mm.discover_provider_models(api_key=api_key, base_url=conn.base_url)
    success = bool(result.get("success"))
    error = _redact(result.get("error") or "", api_key)
    conn.test_status = "ok" if success else "failed"
    conn.test_error = error or None
    conn.tested_at = datetime.now(timezone.utc)
    conn.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "success": success,
        "provider_name": conn.provider_name,
        "model_id": model_id or None,
        "elapsed": result.get("elapsed"),
        "error": error or None,
        "error_code": str(result.get("error_code") or "") or None,
        "test_status": conn.test_status,
    }


@router.get("/api/v1/models")
def list_models(request: Request, db: Session = Depends(db_session)) -> dict:
    record = current_record(request)
    rows = db.execute(
        select(UserModel, ModelConnection)
        .join(ModelConnection, UserModel.connection_id == ModelConnection.id)
        .where(
            UserModel.tenant_id == record.tenant_id,
            UserModel.owner_user_id == record.user_id,
        )
    ).all()
    user = db.get(User, record.user_id)
    default_ref = (user.default_model_ref if user else None) or None
    models = [_model_json(model, conn) for model, conn in rows]
    if record.user_id in platform_model_users():
        models.append(
            {
                "model_ref": PLATFORM_MODEL_REF,
                "model_id": platform_model_name(),
                "display_name": "平台额度",
                "provider_id": "platform",
                "provider_name": "平台额度",
                "connection_id": "",
                "connection_name": "",
                "source": "platform",
                "status": "available",
            }
        )
    return {"models": models, "default_model_ref": default_ref}


@router.post("/api/v1/models/default")
def set_default_model(
    payload: _DefaultIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    ref = (payload.model_ref or "").strip()
    if not ref:
        user.default_model_ref = None
    elif ref == PLATFORM_MODEL_REF:
        if record.user_id not in platform_model_users():
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
        user.default_model_ref = PLATFORM_MODEL_REF
    else:
        model = db.get(UserModel, ref)
        if (
            model is None
            or model.tenant_id != record.tenant_id
            or model.owner_user_id != record.user_id
        ):
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
        user.default_model_ref = model.id
    db.commit()
    return {"default_model_ref": user.default_model_ref}


@router.delete("/api/v1/models/{model_ref}")
def delete_model(
    model_ref: str,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    model = _owned_model(db, record, model_ref)
    _clear_default_if_removed(db, db.get(User, record.user_id), [model.id])
    db.delete(model)
    db.commit()
    return {"deleted": True}
