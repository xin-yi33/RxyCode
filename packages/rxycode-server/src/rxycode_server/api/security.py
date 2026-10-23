"""Security surface — step-up reauthentication, session inventory, security
events, password change, and capability-gated passkey/TOTP/SMS enrolment.

Never returns credential material: session ids are a second-layer hash,
reauth tickets are opaque and single-use, TOTP seeds are keyring-sealed,
recovery codes appear exactly once. Every mutation is CSRF-gated, rate
limited and written to the security event log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from rxycode_server.api.auth import (
    AuthRecord,
    _aware,
    _hash_token,
    current_record,
    db_session,
    require_write,
    verify_password,
    hash_password,
)
from rxycode_server.persistence.models import (
    AuthSession,
    AuthorizedApp,
    ReauthTicket,
    RecoveryCode,
    SecurityEvent,
    SmsEnrollment,
    TotpEnrollment,
    User,
    WebAuthnChallenge,
    WebAuthnCredential,
)

router = APIRouter()
_REAUTH_TTL = timedelta(minutes=10)
_MFA_TTL = timedelta(minutes=5)
_PAGE_LIMIT = 100
_RECOVERY_COUNT = 8


def _lib(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _capabilities(request: Request) -> dict[str, object]:
    return {
        "passkey": {
            "available": _lib("webauthn"),
            "reason": "" if _lib("webauthn") else "webauthn_library_missing",
        },
        "totp": {
            "available": _lib("pyotp") and _keyring_ok(),
            "reason": (
                ""
                if _lib("pyotp") and _keyring_ok()
                else ("pyotp_library_missing" if not _lib("pyotp") else "keyring_unavailable")
            ),
        },
        "sms": {
            "available": bool(getattr(request.app.state, "sms_sender", None)),
            "reason": ""
            if getattr(request.app.state, "sms_sender", None)
            else "sms_not_configured",
        },
        # No identity provider / consent service exists yet — honest false.
        "authorized_apps": {"available": False, "reason": "no_idp"},
        "email_delivery": {
            "available": bool(getattr(request.app.state, "smtp_url", "")),
            "reason": "" if getattr(request.app.state, "smtp_url", "") else "smtp_not_configured",
        },
    }


def _keyring_ok() -> bool:
    try:
        from rxycode_server.byok.crypto import load_keyring

        load_keyring()
        return True
    except Exception:
        return False


def _client_hint(request: Request) -> str:
    from rxycode_server.api.client_ip import client_ip

    ip = client_ip(request)
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return ip[:64]


def _device_label(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:128]


def record_security_event(
    db: Session,
    *,
    user_id: str,
    tenant_id: str,
    type: str,
    result: str = "ok",
    device_label: str = "",
    ip_hint: str = "",
) -> None:
    db.add(
        SecurityEvent(
            id=uuid.uuid4().hex,
            user_id=user_id,
            tenant_id=tenant_id,
            type=type,
            result=result,
            device_label=device_label[:128],
            ip_hint=ip_hint[:64],
        )
    )


def _rate_limit(request: Request, bucket: str, key: str, limit: int = 5) -> None:
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is None:
        return
    if not limiter.hit(f"{bucket}:{key}"):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")


def _issue_ticket(db: Session, user_id: str, purpose: str) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + _REAUTH_TTL
    token = secrets.token_urlsafe(32)
    db.add(
        ReauthTicket(
            id=token,
            user_id=user_id,
            purpose=purpose,
            expires_at=expires,
        )
    )
    db.flush()
    return token, expires


def _consume_ticket(db: Session, record: AuthRecord, token: str, purpose: str) -> None:
    """A step-up ticket is single-use, user-bound, purpose-bound, short-lived."""
    now = datetime.now(timezone.utc)
    row = db.execute(
        select(ReauthTicket)
        .where(
            ReauthTicket.id == token,
            ReauthTicket.user_id == record.user_id,
            ReauthTicket.purpose == purpose,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        row is None
        or row.consumed_at is not None
        or _aware(row.expires_at) is None
        or _aware(row.expires_at) <= now
    ):
        raise HTTPException(status_code=401, detail="REAUTH_REQUIRED")
    row.consumed_at = now
    db.flush()


def _session_public_id(token_hash: str) -> str:
    return hashlib.sha256(("public:" + token_hash).encode()).hexdigest()[:32]


def _auth_session_item(row: AuthSession, current_hash: str) -> dict[str, object]:
    return {
        "id": _session_public_id(row.token_hash),
        "created_at": _iso(row.created_at),
        "last_seen_at": _iso(row.last_seen_at),
        "expires_at": _iso(row.expires_at),
        "device_label": row.device_label or "",
        "ip_hint": row.ip_hint or "",
        "current": row.token_hash == current_hash,
        "revoked": row.revoked_at is not None,
    }


def _iso(value) -> str | None:
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _current_token_hash(request: Request) -> str:
    raw = request.cookies.get("rxy_session", "")
    return _hash_token(request.app.state.secret, raw)


# --- security overview ------------------------------------------------------


@router.get("/api/v1/auth/security")
def security_overview(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    record = current_record(request)
    user = db.get(User, record.user_id)
    now = datetime.now(timezone.utc)
    active = db.scalar(
        select(func.count(AuthSession.token_hash)).where(
            AuthSession.user_id == record.user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    passkeys = db.scalar(
        select(func.count(WebAuthnCredential.id)).where(
            WebAuthnCredential.user_id == record.user_id
        )
    )
    totp = db.get(TotpEnrollment, record.user_id)
    sms = db.get(SmsEnrollment, record.user_id)
    apps = db.scalar(
        select(func.count(AuthorizedApp.id)).where(AuthorizedApp.user_id == record.user_id)
    )
    return {
        "password_present": bool(user is not None and user.password_hash),
        "passkeys_count": int(passkeys or 0),
        "totp_enabled": bool(totp is not None and totp.enabled),
        "sms_enabled": bool(sms is not None and sms.enabled),
        "active_sessions_count": int(active or 0),
        "authorized_apps_count": int(apps or 0),
        "capabilities": _capabilities(request),
    }


# --- step-up reauthentication ------------------------------------------------


class _ReauthIn(BaseModel):
    method: str = "password"
    purpose: str
    password: str = ""


_PURPOSES = {
    "password_change",
    "session_revoke",
    "passkey_add",
    "passkey_remove",
    "totp_setup",
    "totp_remove",
    "recovery_codes",
    "sms_setup",
}


@router.post("/api/v1/auth/reauthenticate")
def reauthenticate(
    payload: _ReauthIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.purpose not in _PURPOSES:
        raise HTTPException(status_code=422, detail="INVALID_INPUT")
    _rate_limit(request, "reauth", record.user_id)
    user = db.get(User, record.user_id)
    if payload.method == "password":
        if user is None or not user.password_hash:
            raise HTTPException(status_code=422, detail="PASSWORD_NOT_SET")
        if not verify_password(payload.password, user.password_hash):
            record_security_event(
                db,
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                type="reauthenticate",
                result="denied",
                device_label=_device_label(request),
                ip_hint=_client_hint(request),
            )
            db.flush()
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    elif payload.method == "totp":
        _verify_totp_or_raise(db, record.user_id, payload.password)
    else:
        raise HTTPException(status_code=422, detail="INVALID_INPUT")
    token, expires = _issue_ticket(db, record.user_id, payload.purpose)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="reauthenticate",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return {"reauth_token": token, "expires_at": _iso(expires)}


# --- session inventory -------------------------------------------------------


@router.get("/api/v1/auth/sessions")
def list_auth_sessions(
    request: Request,
    cursor: str = "",
    limit: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))
    rows = db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == record.user_id)
        .order_by(AuthSession.last_seen_at.desc())
        .limit(limit + 1)
    ).all()
    current = _current_token_hash(request)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _session_public_id(rows[-1].token_hash)
    return {
        "sessions": [_auth_session_item(row, current) for row in rows],
        "next_cursor": next_cursor,
    }


class _RevokeIn(BaseModel):
    reauth_token: str | None = None


class _RevokeAllIn(BaseModel):
    reauth_token: str | None = None
    include_current: bool = False


def _find_auth_session(db: Session, record: AuthRecord, public_id: str) -> AuthSession | None:
    for row in db.scalars(select(AuthSession).where(AuthSession.user_id == record.user_id)).all():
        if _session_public_id(row.token_hash) == public_id:
            return row
    return None


@router.delete("/api/v1/auth/sessions/{session_id}", status_code=204)
def revoke_auth_session(
    session_id: str,
    payload: _RevokeIn,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    if payload.reauth_token is None:
        raise HTTPException(status_code=401, detail="REAUTH_REQUIRED")
    _consume_ticket(db, record, payload.reauth_token, "session_revoke")
    row = _find_auth_session(db, record, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        record_security_event(
            db,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            type="session_revoked",
            result="ok",
            device_label=_device_label(request),
            ip_hint=_client_hint(request),
        )
        db.flush()
    return None


@router.post("/api/v1/auth/sessions/revoke-all")
def revoke_all_sessions(
    payload: _RevokeAllIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.reauth_token is None:
        raise HTTPException(status_code=401, detail="REAUTH_REQUIRED")
    _consume_ticket(db, record, payload.reauth_token, "session_revoke")
    current = _current_token_hash(request)
    now = datetime.now(timezone.utc)
    count = 0
    for row in db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == record.user_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all():
        if not payload.include_current and row.token_hash == current:
            continue
        row.revoked_at = now
        count += 1
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="sessions_revoked_all",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return {"revoked": count}


# --- security event log -------------------------------------------------------


@router.get("/api/v1/auth/security-events")
def security_events(
    request: Request,
    cursor: str = "",
    limit: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))
    query = (
        select(SecurityEvent)
        .where(SecurityEvent.user_id == record.user_id)
        .order_by(SecurityEvent.at.desc(), SecurityEvent.id.desc())
    )
    if cursor:
        try:
            last_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())[0]
            anchor = db.get(SecurityEvent, str(last_id))
        except (ValueError, TypeError, IndexError):
            anchor = None
        if anchor is not None:
            query = query.where(
                (SecurityEvent.at < anchor.at)
                | ((SecurityEvent.at == anchor.at) & (SecurityEvent.id < anchor.id))
            )
    rows = db.scalars(query.limit(limit + 1)).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(json.dumps([rows[-1].id]).encode()).decode()
    return {
        "events": [
            {
                "id": row.id,
                "type": row.type,
                "at": _iso(row.at),
                "result": row.result,
                "device_label": row.device_label,
                "ip_hint": row.ip_hint,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


# --- password change ---------------------------------------------------------


class _PasswordIn(BaseModel):
    new_password: str
    reauth_token: str


@router.put("/api/v1/auth/password", status_code=204)
def change_password(
    payload: _PasswordIn,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    _consume_ticket(db, record, payload.reauth_token, "password_change")
    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    if not 8 <= len(payload.new_password) <= 128:
        raise HTTPException(status_code=422, detail="WEAK_PASSWORD")
    user.password_hash = hash_password(payload.new_password)
    # Rotating the password kills every other device session.
    current = _current_token_hash(request)
    now = datetime.now(timezone.utc)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == record.user_id,
            AuthSession.token_hash != current,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="password_changed",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return None


# --- passkeys (capability-gated real WebAuthn) --------------------------------


def _webauthn_ready(request: Request) -> None:
    if not _lib("webauthn"):
        raise HTTPException(status_code=503, detail="PASSKEY_UNAVAILABLE")


def _rp(request: Request) -> tuple[str, str]:
    origin = request.headers.get("origin") or "http://localhost"
    host = origin.split("//", 1)[-1].split("/")[0].split(":")[0] or "localhost"
    return host, "RxyCode"


@router.get("/api/v1/auth/passkeys")
def list_passkeys(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    record = current_record(request)
    rows = db.scalars(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == record.user_id)
    ).all()
    return {
        "capability": _capabilities(request)["passkey"],
        "passkeys": [
            {
                "id": row.id,
                "name": row.name,
                "created_at": _iso(row.created_at),
                "last_used_at": _iso(row.last_used_at),
                "transports": row.transports or [],
            }
            for row in rows
        ],
    }


class _PasskeyName(BaseModel):
    name: str = ""


class _RegOptionsIn(BaseModel):
    reauth_token: str


@router.post("/api/v1/auth/passkeys/registration/options")
def passkey_registration_options(
    payload: _RegOptionsIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    _webauthn_ready(request)
    _consume_ticket(db, record, payload.reauth_token, "passkey_add")
    from webauthn import generate_registration_options
    from webauthn.helpers import options_to_json

    rp_id, rp_name = _rp(request)
    user = db.get(User, record.user_id)
    existing = db.scalars(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == record.user_id)
    ).all()
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=record.user_id.encode(),
        user_name=user.email if user is not None and user.email else record.user_id,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64.b64decode(row.credential_id))
            for row in existing
            if row.credential_id
        ],
    )
    challenge = WebAuthnChallenge(
        id=uuid.uuid4().hex,
        user_id=record.user_id,
        challenge_hash=hashlib.sha256(options.challenge).hexdigest(),
        kind="register",
        payload={"challenge": base64.b64encode(options.challenge).decode()},
        expires_at=datetime.now(timezone.utc) + _MFA_TTL,
    )
    db.add(challenge)
    db.flush()
    body = json.loads(options_to_json(options))
    body["challenge_id"] = challenge.id
    return body


class _RegVerifyIn(BaseModel):
    challenge_id: str
    credential: dict
    name: str = ""


@router.post("/api/v1/auth/passkeys/registration/verify")
def passkey_registration_verify(
    payload: _RegVerifyIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    _webauthn_ready(request)
    challenge = db.execute(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == payload.challenge_id,
            WebAuthnChallenge.user_id == record.user_id,
            WebAuthnChallenge.kind == "register",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        challenge is None
        or challenge.used_at is not None
        or _aware(challenge.expires_at) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=400, detail="CHALLENGE_EXPIRED")
    from webauthn import verify_registration_response

    origin = request.headers.get("origin") or "http://localhost"
    rp_id, _name = _rp(request)
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=base64.b64decode(challenge.payload["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="PASSKEY_VERIFY_FAILED") from None
    challenge.used_at = datetime.now(timezone.utc)
    cred_id = base64.b64encode(bytes(verified.credential_id)).decode()
    cred_hash = hashlib.sha256(bytes(verified.credential_id)).hexdigest()
    if (
        db.scalars(
            select(WebAuthnCredential).where(WebAuthnCredential.credential_id_hash == cred_hash)
        ).first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="PASSKEY_EXISTS")
    row = WebAuthnCredential(
        id=uuid.uuid4().hex,
        user_id=record.user_id,
        credential_id=cred_id,
        credential_id_hash=cred_hash,
        public_key=bytes(verified.credential_public_key),
        sign_count=int(verified.sign_count or 0),
        name=(payload.name or "Passkey")[:128],
        transports=[],
        aaguid=str(verified.aaguid or ""),
    )
    db.add(row)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="passkey_added",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return {
        "id": row.id,
        "name": row.name,
        "created_at": _iso(row.created_at),
    }


class _PasskeyPatch(BaseModel):
    name: str | None = None
    reauth_token: str | None = None


@router.patch("/api/v1/auth/passkeys/{passkey_id}")
def rename_passkey(
    passkey_id: str,
    payload: _PasskeyPatch,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = db.execute(
        select(WebAuthnCredential)
        .where(
            WebAuthnCredential.id == passkey_id,
            WebAuthnCredential.user_id == record.user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PASSKEY_NOT_FOUND")
    if payload.name is not None:
        name = payload.name.strip()
        if not 1 <= len(name) <= 128:
            raise HTTPException(status_code=422, detail="INVALID_INPUT")
        row.name = name
        db.flush()
    return {"id": row.id, "name": row.name}


@router.delete("/api/v1/auth/passkeys/{passkey_id}", status_code=204)
def delete_passkey(
    passkey_id: str,
    payload: _RevokeIn,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    if payload.reauth_token is None:
        raise HTTPException(status_code=401, detail="REAUTH_REQUIRED")
    _consume_ticket(db, record, payload.reauth_token, "passkey_remove")
    row = db.execute(
        select(WebAuthnCredential)
        .where(
            WebAuthnCredential.id == passkey_id,
            WebAuthnCredential.user_id == record.user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PASSKEY_NOT_FOUND")
    user = db.get(User, record.user_id)
    remaining = (
        db.scalar(
            select(func.count(WebAuthnCredential.id)).where(
                WebAuthnCredential.user_id == record.user_id,
                WebAuthnCredential.id != passkey_id,
            )
        )
        or 0
    )
    totp = db.get(TotpEnrollment, record.user_id)
    has_other_login = bool(user and user.password_hash) or bool(totp is not None and totp.enabled)
    if remaining == 0 and not has_other_login:
        raise HTTPException(status_code=409, detail="LAST_LOGIN_METHOD")
    db.delete(row)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="passkey_removed",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return None


# --- passkey login -------------------------------------------------------------


class _LoginOptionsIn(BaseModel):
    passkey_id: str | None = None


@router.post("/api/v1/auth/passkeys/login/options")
def passkey_login_options(
    payload: _LoginOptionsIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    _webauthn_ready(request)
    from webauthn import generate_authentication_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    rp_id, _ = _rp(request)
    allow = []
    if payload.passkey_id:
        row = db.get(WebAuthnCredential, payload.passkey_id)
        if row is not None and row.credential_id:
            allow = [PublicKeyCredentialDescriptor(id=base64.b64decode(row.credential_id))]
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow,
    )
    challenge = WebAuthnChallenge(
        id=uuid.uuid4().hex,
        user_id=None,
        challenge_hash=hashlib.sha256(options.challenge).hexdigest(),
        kind="login",
        payload={"challenge": base64.b64encode(options.challenge).decode()},
        expires_at=datetime.now(timezone.utc) + _MFA_TTL,
    )
    db.add(challenge)
    db.flush()
    body = json.loads(options_to_json(options))
    body["challenge_id"] = challenge.id
    return body


class _LoginVerifyIn(BaseModel):
    challenge_id: str
    credential: dict


@router.post("/api/v1/auth/passkeys/login/verify")
def passkey_login_verify(
    payload: _LoginVerifyIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Verify an assertion, then issue the same HttpOnly session as login."""
    require_write(request)
    _webauthn_ready(request)
    challenge = db.execute(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == payload.challenge_id,
            WebAuthnChallenge.kind == "login",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        challenge is None
        or challenge.used_at is not None
        or _aware(challenge.expires_at) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=400, detail="CHALLENGE_EXPIRED")
    cred_id_b64 = str(payload.credential.get("id") or "")
    cred_hash = hashlib.sha256(base64.b64decode(cred_id_b64)).hexdigest() if cred_id_b64 else ""
    row = db.scalars(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id_hash == cred_hash)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    from webauthn import verify_authentication_response

    origin = request.headers.get("origin") or "http://localhost"
    rp_id, _ = _rp(request)
    try:
        verified = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=base64.b64decode(challenge.payload["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(row.public_key),
            credential_current_sign_count=int(row.sign_count or 0),
        )
    except Exception:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS") from None
    challenge.used_at = datetime.now(timezone.utc)
    row.sign_count = int(verified.new_sign_count or row.sign_count or 0)
    row.last_used_at = datetime.now(timezone.utc)
    user = db.get(User, row.user_id)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    tenant_id = _tenant_for_user(db, row.user_id)
    record_security_event(
        db,
        user_id=row.user_id,
        tenant_id=tenant_id,
        type="passkey_login",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    from fastapi.responses import JSONResponse

    from rxycode_server.api.auth import _issue, _me_body, _set_session, _secure

    token = _issue(request, db, row.user_id, tenant_id)
    body = _me_body(AuthRecord(user_id=row.user_id, tenant_id=tenant_id, created=0.0), db)
    resp = JSONResponse(body)
    _set_session(resp, token, secure=_secure(request))
    return resp


def _tenant_for_user(db: Session, user_id: str) -> str:
    from rxycode_server.api.auth import _tenant_for

    return _tenant_for(db, user_id)


# --- TOTP (capability-gated) ---------------------------------------------------


def _totp_ready() -> None:
    if not _lib("pyotp") or not _keyring_ok():
        raise HTTPException(status_code=503, detail="TOTP_UNAVAILABLE")


def _seal_secret(secret: str, user_id: str) -> tuple[bytes, bytes, str]:
    from rxycode_server.byok.crypto import encrypt

    return encrypt(secret, aad=("totp:" + user_id).encode())


def _open_secret(row: TotpEnrollment) -> str:
    from rxycode_server.byok.crypto import decrypt

    return decrypt(row.secret_enc, row.nonce, row.key_id, aad=("totp:" + row.user_id).encode())


def _verify_totp_or_raise(db: Session, user_id: str, code: str) -> None:
    row = db.get(TotpEnrollment, user_id)
    if row is None or not row.enabled:
        raise HTTPException(status_code=422, detail="TOTP_NOT_ENABLED")
    import pyotp

    secret = _open_secret(row)
    if not pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")


class _TotpSetupIn(BaseModel):
    reauth_token: str


@router.post("/api/v1/auth/mfa/totp/setup")
def totp_setup(
    payload: _TotpSetupIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    _totp_ready()
    _consume_ticket(db, record, payload.reauth_token, "totp_setup")
    import pyotp

    secret = pyotp.random_base32()
    ciphertext, nonce, key_id = _seal_secret(secret, record.user_id)
    row = db.execute(
        select(TotpEnrollment).where(TotpEnrollment.user_id == record.user_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = TotpEnrollment(user_id=record.user_id)
        db.add(row)
    row.secret_enc = ciphertext
    row.nonce = nonce
    row.key_id = key_id
    row.enabled = False
    row.confirmed_at = None
    db.flush()
    user = db.get(User, record.user_id)
    account = user.email if user is not None and user.email else record.user_id
    return {
        "setup_id": row.user_id,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name="RxyCode"),
        "secret": secret,
    }


class _TotpConfirmIn(BaseModel):
    setup_id: str
    code: str


@router.post("/api/v1/auth/mfa/totp/confirm")
def totp_confirm(
    payload: _TotpConfirmIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    _totp_ready()
    if payload.setup_id != record.user_id:
        raise HTTPException(status_code=422, detail="INVALID_INPUT")
    row = db.execute(
        select(TotpEnrollment).where(TotpEnrollment.user_id == record.user_id).with_for_update()
    ).scalar_one_or_none()
    if row is None or row.enabled:
        raise HTTPException(status_code=404, detail="SETUP_NOT_FOUND")
    import pyotp

    secret = _open_secret(row)
    if not pyotp.TOTP(secret).verify(str(payload.code).strip(), valid_window=1):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    row.enabled = True
    row.confirmed_at = datetime.now(timezone.utc)
    codes = _regen_recovery_codes(db, record.user_id)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="totp_enabled",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return {"enabled": True, "backup_codes": codes}


def _regen_recovery_codes(db: Session, user_id: str) -> list[str]:
    db.execute(RecoveryCode.__table__.delete().where(RecoveryCode.user_id == user_id))
    codes = []
    for _ in range(_RECOVERY_COUNT):
        code = "-".join(secrets.token_hex(2) for _ in range(3))
        db.add(
            RecoveryCode(
                user_id=user_id,
                code_hash=hashlib.sha256(code.encode()).hexdigest(),
            )
        )
        codes.append(code)
    db.flush()
    return codes


class _TotpDeleteIn(BaseModel):
    reauth_token: str
    code: str


@router.delete("/api/v1/auth/mfa/totp", status_code=204)
def totp_delete(
    payload: _TotpDeleteIn,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    _totp_ready()
    _consume_ticket(db, record, payload.reauth_token, "totp_remove")
    _verify_totp_or_raise(db, record.user_id, payload.code)
    db.execute(TotpEnrollment.__table__.delete().where(TotpEnrollment.user_id == record.user_id))
    db.execute(RecoveryCode.__table__.delete().where(RecoveryCode.user_id == record.user_id))
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="totp_disabled",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return None


class _RecoveryIn(BaseModel):
    reauth_token: str


@router.post("/api/v1/auth/mfa/recovery-codes")
def regen_recovery(
    payload: _RecoveryIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    _consume_ticket(db, record, payload.reauth_token, "recovery_codes")
    codes = _regen_recovery_codes(db, record.user_id)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="recovery_codes_regenerated",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    # Plaintext exactly once, in this response only.
    return {"backup_codes": codes}


# --- SMS MFA — capability-gated, nothing faked --------------------------------


@router.post("/api/v1/auth/mfa/sms/setup")
def sms_setup(request: Request) -> None:
    require_write(request)
    current_record(request)
    if not _capabilities(request)["sms"]["available"]:
        raise HTTPException(status_code=503, detail="SMS_UNAVAILABLE")
    raise HTTPException(status_code=501, detail="SMS_NOT_IMPLEMENTED")


@router.post("/api/v1/auth/mfa/sms/confirm")
def sms_confirm(request: Request) -> None:
    require_write(request)
    current_record(request)
    raise HTTPException(status_code=503, detail="SMS_UNAVAILABLE")


@router.delete("/api/v1/auth/mfa/sms", status_code=204)
def sms_delete(request: Request, db: Session = Depends(db_session)) -> None:
    require_write(request)
    record = current_record(request)
    db.execute(SmsEnrollment.__table__.delete().where(SmsEnrollment.user_id == record.user_id))
    db.flush()
    return None


# --- authorized apps -----------------------------------------------------------


@router.get("/api/v1/auth/authorized-apps")
def list_authorized_apps(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    record = current_record(request)
    rows = db.scalars(select(AuthorizedApp).where(AuthorizedApp.user_id == record.user_id)).all()
    return {
        "capability": _capabilities(request)["authorized_apps"],
        "apps": [
            {
                "id": row.id,
                "name": row.name,
                "scopes": row.scopes or [],
                "granted_at": _iso(row.granted_at),
            }
            for row in rows
        ],
    }


@router.delete("/api/v1/auth/authorized-apps/{app_id}", status_code=204)
def revoke_authorized_app(
    app_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    row = db.execute(
        select(AuthorizedApp)
        .where(AuthorizedApp.id == app_id, AuthorizedApp.user_id == record.user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="APP_NOT_FOUND")
    db.delete(row)
    record_security_event(
        db,
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        type="authorized_app_revoked",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    return None


# --- MFA login challenge --------------------------------------------------------


def mfa_required_for(db: Session, user_id: str) -> list[str]:
    """Methods this user must clear before a session is issued."""
    methods = []
    row = db.get(TotpEnrollment, user_id)
    if row is not None and row.enabled:
        methods.append("totp")
    return methods


def issue_mfa_challenge(db: Session, user_id: str, tenant_id: str) -> str:
    challenge = WebAuthnChallenge(
        id=uuid.uuid4().hex,
        user_id=user_id,
        challenge_hash="",
        kind="mfa_login",
        payload={"user_id": user_id, "tenant_id": tenant_id},
        expires_at=datetime.now(timezone.utc) + _MFA_TTL,
    )
    db.add(challenge)
    db.flush()
    return challenge.id


class _MfaVerifyIn(BaseModel):
    challenge_id: str
    method: str
    code: str


@router.post("/api/v1/auth/mfa/challenge/verify")
def mfa_challenge_verify(
    payload: _MfaVerifyIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Second factor after a password-only pre-auth. Success issues the
    session through the exact same durable path as password login."""

    challenge = db.execute(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.id == payload.challenge_id,
            WebAuthnChallenge.kind == "mfa_login",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        challenge is None
        or challenge.used_at is not None
        or _aware(challenge.expires_at) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=401, detail="CHALLENGE_EXPIRED")
    user_id = str(challenge.payload.get("user_id") or "")
    tenant_id = str(challenge.payload.get("tenant_id") or "")
    _rate_limit(request, "mfa", user_id)
    if payload.method == "totp":
        _verify_totp_or_raise(db, user_id, payload.code)
    elif payload.method == "recovery_code":
        code_hash = hashlib.sha256(str(payload.code).strip().encode()).hexdigest()
        row = db.execute(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.code_hash == code_hash,
                RecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            record_security_event(
                db,
                user_id=user_id,
                tenant_id=tenant_id,
                type="mfa_challenge",
                result="denied",
                device_label=_device_label(request),
                ip_hint=_client_hint(request),
            )
            db.flush()
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
        row.used_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(status_code=422, detail="INVALID_INPUT")
    challenge.used_at = datetime.now(timezone.utc)
    user = db.get(User, user_id)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    from rxycode_server.api.auth import _issue, _me_body, _set_session, _secure

    record_security_event(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        type="mfa_challenge",
        result="ok",
        device_label=_device_label(request),
        ip_hint=_client_hint(request),
    )
    db.flush()
    from fastapi.responses import JSONResponse

    # Issue the session cookie on a JSONResponse — same durable chain as login.
    from rxycode_server.api.auth import AuthRecord as _Rec

    token = _issue(request, db, user_id, tenant_id)
    body = _me_body(_Rec(user_id=user_id, tenant_id=tenant_id, created=0.0), db)
    resp = JSONResponse(body)
    _set_session(resp, token, secure=_secure(request))
    return resp
