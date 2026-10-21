"""GitHub OAuth with PKCE, registration, password login, and the cookie session.

WEB-W9-B1: browser sessions are durable rows in ``auth_sessions`` — a cookie
token's HMAC digest is the row key, expiry is wall-clock (7 days, sliding:
the row renews once it has not been seen for over a day), and a revoked or
disabled user's session never authorizes again, across restarts and
replicas. OAuth ``state`` rows live in ``oauth_states`` so a different
replica can finish the callback. Registration is gated by
``app.state.registration`` (``invite``/``open``/``closed``) and invites are
single-use hashes — plaintext codes are never stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rxycode_server.persistence.models import (
    AuthSession,
    Invite,
    Membership,
    OAuthState,
    Organization,
    PasswordReset,
    Project,
    User,
)

log = logging.getLogger(__name__)
router = APIRouter()
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
_SESSION_TTL = timedelta(days=7)
_SESSION_RENEW_AFTER = timedelta(days=1)
_STATE_TTL = timedelta(minutes=10)
_RESET_TTL = timedelta(minutes=30)
_REGISTRATION_MODES = ("invite", "open", "closed")
_DEFAULT_PROJECT_NAME = "默认项目"
_DUMMY_HASH = (
    "scrypt$16384$8$1$"
    + base64.b64encode(b"rxycode-dummy-s1").decode()
    + "$"
    + base64.b64encode(b"0" * 32).decode()
)


@dataclass
class AuthRecord:
    user_id: str
    tenant_id: str
    created: float


def db_session(request: Request) -> Iterator[Session]:
    db = Session(request.app.state.engine)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _hash_token(secret: str, token: str) -> str:
    return hmac.new(secret.encode(), token.encode(), "sha256").hexdigest()


def invite_digest(code: str) -> str:
    """SHA-256 digest of a plaintext invite code — the only thing ever stored."""
    return hashlib.sha256(code.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return (
        "scrypt$16384$8$1$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(derived).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$", 5)
        n, r, p = int(n_s), int(r_s), int(p_s)
        if scheme != "scrypt" or n < 2 or (n & (n - 1)) or r < 1 or p < 1:
            return False
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=n,
            r=r,
            p=p,
            dklen=len(expected) or 32,
        )
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        return False


def _normalize_email(raw: str) -> str:
    return raw.strip().lower()


def _check_email(email: str) -> None:
    parts = email.split("@")
    if (
        not email
        or len(email) > 254
        or len(parts) != 2
        or not parts[0]
        or not parts[1]
        or "." not in parts[1]
    ):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class _Window:
    """Fixed-window counter — per replica, resets on restart (spec's intent)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.buckets: dict[tuple[str, int], int] = {}

    def hit(self, key: str) -> bool:
        window = int(time.monotonic()) // 60
        bucket = (key, window)
        seen = self.buckets.get(bucket, 0)
        if seen >= self.limit:
            return False
        self.buckets[bucket] = seen + 1
        if len(self.buckets) > 4096:
            self.buckets = {k: v for k, v in self.buckets.items() if k[1] >= window - 1}
        return True


class AuthRateLimit:
    """Per-IP 10/min + per-email 5/min on /auth/register and /auth/login."""

    def __init__(self) -> None:
        self.ip = _Window(10)
        self.email = _Window(5)

    def check(self, route: str, ip: str, email: str) -> None:
        if not self.ip.hit(f"{route}:ip:{ip}") or not self.email.hit(
            f"{route}:email:{email}"
        ):
            raise HTTPException(status_code=429, detail="RATE_LIMITED")


def _secure(request: Request) -> bool:
    return bool(request.app.state.secure)


def require_write(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if origin not in request.app.state.allowed_origins:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    cookie = request.cookies.get("rxy_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="FORBIDDEN")


def _lookup_session(app, raw: str) -> AuthRecord | None:
    digest = _hash_token(app.state.secret, raw)
    # Tests and tooling may still inject a session into a per-process dict
    # (the standalone device gateway keeps all of its sessions there);
    # production create_app never sets it, so the durable row is authoritative.
    record = getattr(app.state, "sessions", {}).get(digest)
    if record is not None:
        if time.monotonic() - record.created > _SESSION_TTL_SECONDS:
            return None
        return record
    engine = getattr(app.state, "engine", None)
    if engine is None:
        return None
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        row = db.get(AuthSession, digest)
        if row is None or row.revoked_at is not None or _aware(row.expires_at) <= now:
            return None
        user = db.get(User, row.user_id)
        if user is None or user.disabled_at is not None:
            return None
        if now - _aware(row.last_seen_at) > _SESSION_RENEW_AFTER:
            row.last_seen_at = now
            row.expires_at = now + _SESSION_TTL
            db.commit()
        return AuthRecord(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            created=_aware(row.created_at).timestamp(),
        )


def current_record(request: Request) -> AuthRecord:
    raw = request.cookies.get("rxy_session", "")
    if not raw:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    record = _lookup_session(request.app, raw)
    if record is None:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    return record


def _drop_current(request: Request, db: Session | None = None) -> None:
    raw = request.cookies.get("rxy_session", "")
    if not raw:
        return
    digest = _hash_token(request.app.state.secret, raw)
    getattr(request.app.state, "sessions", {}).pop(digest, None)
    if getattr(request.app.state, "engine", None) is None:
        return
    if db is not None:
        row = db.get(AuthSession, digest)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)


def _issue(request: Request, db: Session | None, user_id: str, tenant_id: str) -> str:
    token = secrets.token_urlsafe(32)
    digest = _hash_token(request.app.state.secret, token)
    if getattr(request.app.state, "engine", None) is None:
        request.app.state.sessions[digest] = AuthRecord(
            user_id=user_id, tenant_id=tenant_id, created=time.monotonic()
        )
        return token
    now = datetime.now(timezone.utc)
    db.add(
        AuthSession(
            token_hash=digest,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=now,
            expires_at=now + _SESSION_TTL,
            last_seen_at=now,
        )
    )
    return token


def _set_session(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        "rxy_session",
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=_SESSION_TTL_SECONDS,
    )


def _same(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def _local_account(db: Session) -> tuple[User, Organization]:
    """Local mode has one user. A later login keeps that user and tenant."""
    user = db.scalars(select(User).where(User.kind == "local")).one_or_none()
    if user is not None:
        tenant_id = db.scalars(select(Membership.tenant_id).where(Membership.user_id == user.id)).one()
        org = db.scalars(select(Organization).where(Organization.tenant_id == tenant_id)).one()
        return user, org
    user = User(id=uuid.uuid4().hex, github_id=None, kind="local")
    org = Organization(id=uuid.uuid4().hex, tenant_id=uuid.uuid4().hex)
    db.add(user)
    db.add(org)
    db.add(Membership(id=uuid.uuid4().hex, tenant_id=org.tenant_id, user_id=user.id, role="owner"))
    db.flush()
    return user, org


def _github_account(db: Session, github_id: str) -> tuple[User, str]:
    user = db.scalars(select(User).where(User.github_id == github_id)).one_or_none()
    if user is not None:
        tenant_id = db.scalars(select(Membership.tenant_id).where(Membership.user_id == user.id)).one()
        return user, tenant_id
    user = User(id=uuid.uuid4().hex, github_id=github_id, kind="github")
    org = Organization(id=uuid.uuid4().hex, tenant_id=uuid.uuid4().hex)
    db.add(user)
    db.add(org)
    db.add(Membership(id=uuid.uuid4().hex, tenant_id=org.tenant_id, user_id=user.id, role="owner"))
    db.flush()
    return user, org.tenant_id


def _tenant_for(db: Session, user_id: str) -> str:
    row = db.scalars(
        select(Membership.tenant_id).where(Membership.user_id == user_id).limit(1)
    ).first()
    return row or ""


def _ensure_default_project(db: Session, tenant_id: str) -> str:
    """Create the tenant's catch-all project — 默认项目 — and return its id."""
    project = Project(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        name=_DEFAULT_PROJECT_NAME,
        repo_config={},
    )
    db.add(project)
    db.flush()
    return project.id


def _default_project_id(db: Session, user: User | None, tenant_id: str) -> str | None:
    if user is None:
        return None
    if not user.default_project_id:
        user.default_project_id = _ensure_default_project(db, tenant_id)
    return user.default_project_id


def _capabilities(request: Request) -> dict[str, object]:
    state = request.app.state
    if getattr(state, "smtp_url", ""):
        reset_delivery = "smtp"
    elif state.mode == "local":
        reset_delivery = "inline"
    elif getattr(state, "reset_operator_log", False):
        reset_delivery = "operator-log"
    else:
        reset_delivery = "none"
    return {
        "mode": state.mode,
        "password": True,
        "registration": getattr(state, "registration", "invite"),
        "github": bool(
            getattr(state, "github_client_id", "")
            and getattr(state, "github_client_secret", "")
            and getattr(state, "github_redirect_uri", "")
        ),
        "local": state.mode == "local",
        # A reset link is deliverable over SMTP, handed back inline in local
        # dev mode, or logged for the operator when explicitly enabled.
        # Cloud without any of these cannot deliver — hide the flow.
        "reset_delivery": reset_delivery,
        "password_reset": reset_delivery != "none",
    }


def _me_body(record: AuthRecord, db: Session) -> dict[str, object]:
    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    default_project_id = _default_project_id(db, user, record.tenant_id)
    org = db.scalars(
        select(Organization).where(Organization.tenant_id == record.tenant_id)
    ).one_or_none()
    role = db.scalars(
        select(Membership.role).where(
            Membership.user_id == record.user_id,
            Membership.tenant_id == record.tenant_id,
        )
    ).first()
    return {
        "user": {
            "id": user.id,
            "kind": user.kind,
            "email": user.email,
            "display_name": user.display_name,
            "github_id": user.github_id,
        },
        "organization": {
            "id": org.id if org is not None else "",
            "tenant_id": record.tenant_id,
        },
        "membership": {"role": role or ""},
        "default_project_id": default_project_id,
    }


def exchange_github_code(request: Request, code: str, verifier: str) -> str:
    """Trade a PKCE code at GitHub. The access token is not stored or returned."""
    app = request.app
    payload = {
        "client_id": app.state.github_client_id,
        "client_secret": app.state.github_client_secret,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": app.state.github_redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(transport=app.state.github_transport) as client:
        token_response = client.post(
            "https://github.com/login/oauth/access_token",
            data=payload,
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()
        access_token = str(token_response.json().get("access_token", ""))
        user_response = client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        user_response.raise_for_status()
        github_id = str(user_response.json()["id"])
    return github_id


@router.get("/api/v1/auth/csrf")
def issue_csrf(request: Request, response: Response) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        "rxy_csrf",
        token,
        httponly=False,
        secure=_secure(request),
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


@router.get("/api/v1/auth/capabilities")
def capabilities(request: Request) -> dict[str, object]:
    return _capabilities(request)


@router.post("/api/v1/auth/register", status_code=201)
def register(
    request: Request,
    response: Response,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    email = _normalize_email(str(payload.get("email") or ""))
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check("register", request.client.host if request.client else "-", email)
    _check_email(email)
    password = str(payload.get("password") or "")
    if not 8 <= len(password) <= 128:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    mode = getattr(request.app.state, "registration", "invite")
    if mode not in _REGISTRATION_MODES:
        mode = "invite"
    if mode == "closed":
        raise HTTPException(status_code=403, detail="REGISTRATION_CLOSED")
    if mode == "invite":
        # Atomic consumption: a concurrent registrar cannot spend the same
        # seat, and an EMAIL_TAKEN rollback below returns the seat too.
        code = str(payload.get("invite_code") or "").strip()
        now = datetime.now(timezone.utc)
        claimed = db.execute(
            update(Invite)
            .where(
                Invite.code_hash == invite_digest(code),
                Invite.used < Invite.max_uses,
                or_(Invite.expires_at.is_(None), Invite.expires_at > now),
            )
            .values(used=Invite.used + 1)
            .returning(Invite.code_hash)
        ).first()
        if claimed is None:
            raise HTTPException(status_code=403, detail="INVITE_INVALID")
    tenant_id = uuid.uuid4().hex
    user = User(
        id=uuid.uuid4().hex,
        kind="email",
        email=email,
        password_hash=hash_password(password),
        display_name=str(payload.get("display_name") or "").strip() or None,
    )
    org = Organization(id=uuid.uuid4().hex, tenant_id=tenant_id)
    db.add(user)
    db.add(org)
    db.add(
        Membership(
            id=uuid.uuid4().hex, tenant_id=tenant_id, user_id=user.id, role="owner"
        )
    )
    try:
        user.default_project_id = _ensure_default_project(db, tenant_id)
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="EMAIL_TAKEN") from None
    _set_session(
        response,
        _issue(request, db, user.id, tenant_id),
        secure=_secure(request),
    )
    return _me_body(AuthRecord(user_id=user.id, tenant_id=tenant_id, created=0.0), db)


@router.post("/api/v1/auth/login")
def password_login(
    request: Request,
    response: Response,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    email = _normalize_email(str(payload.get("email") or ""))
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check("login", request.client.host if request.client else "-", email)
    user = db.scalars(select(User).where(User.email == email).limit(1)).first()
    # Always run one scrypt so unknown-email and wrong-password look alike.
    stored = user.password_hash if user is not None and user.password_hash else _DUMMY_HASH
    if user is None or not verify_password(str(payload.get("password") or ""), stored):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    if user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    _drop_current(request, db)
    tenant_id = _tenant_for(db, user.id)
    _set_session(response, _issue(request, db, user.id, tenant_id), secure=_secure(request))
    return _me_body(AuthRecord(user_id=user.id, tenant_id=tenant_id, created=0.0), db)


@router.post("/api/v1/auth/forgot")
def forgot_password(
    request: Request,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Issue a reset token. Always 200 — the shape never reveals whether the
    email exists. Delivery: SMTP when configured; in local dev mode without
    SMTP the link is returned inline (loopback-only gateway, single user)."""
    require_write(request)
    email = _normalize_email(str(payload.get("email") or ""))
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check("forgot", request.client.host if request.client else "-", email)
    user = db.scalars(
        select(User).where(User.email == email).limit(1)
    ).first()
    token = secrets.token_urlsafe(32)
    reset_url = f"{request.headers.get('origin', '')}/reset?token={token}"
    body: dict[str, object] = {"ok": True}
    if (
        user is None
        or user.kind != "email"
        or user.disabled_at is not None
        or not user.password_hash
    ):
        return body
    now = datetime.now(timezone.utc)
    # Only the newest link works: outstanding tokens for this user are spent.
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=now)
    )
    db.add(
        PasswordReset(
            token_hash=_hash_token(request.app.state.secret, token),
            user_id=user.id,
            created_at=now,
            expires_at=now + _RESET_TTL,
        )
    )
    db.flush()
    smtp_url = str(getattr(request.app.state, "smtp_url", "") or "")
    if smtp_url:
        from rxycode_server.mailer import send_mail

        send_mail(
            smtp_url,
            to=email,
            subject="RxyCode 密码重置",
            sender=str(getattr(request.app.state, "smtp_from", "") or ""),
            body=(
                "30 分钟内打开此链接重置密码（一次性，过期失效）：\n\n"
                f"{reset_url}\n\n如果不是你本人操作，忽略本邮件即可。"
            ),
        )
    elif request.app.state.mode == "local":
        body["reset_url"] = reset_url
        body["delivery"] = "inline"
    elif getattr(request.app.state, "reset_operator_log", False):
        # Operator outbox for self-hosted single-admin deployments: the link
        # goes to the api log (log readers already hold database access), the
        # response only names the channel — never the URL.
        log.warning(
            "password reset link for %s (operator outbox, no SMTP configured): %s",
            email,
            reset_url,
        )
        body["delivery"] = "operator-log"
    return body


@router.post("/api/v1/auth/reset")
def reset_password(
    request: Request,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Redeem a reset token: sets the password and revokes every session."""
    require_write(request)
    token = str(payload.get("token") or "")
    password = str(payload.get("password") or "")
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check(
            "reset",
            request.client.host if request.client else "-",
            f"tk:{token[:12]}",
        )
    if not 8 <= len(password) <= 128:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    now = datetime.now(timezone.utc)
    row = db.get(PasswordReset, _hash_token(request.app.state.secret, token))
    user = db.get(User, row.user_id) if row is not None else None
    if (
        row is None
        or row.used_at is not None
        or _aware(row.expires_at) <= now
        or user is None
        or user.disabled_at is not None
    ):
        raise HTTPException(status_code=400, detail="RESET_INVALID")
    user.password_hash = hash_password(password)
    row.used_at = now
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return {"ok": True}


@router.post("/api/v1/auth/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(db_session),
) -> Response:
    require_write(request)
    _drop_current(request, db)
    # The injected Response is replaced by this one — clear the cookie on the
    # response actually returned, with the same attrs the setter used.
    response = Response(status_code=204)
    response.delete_cookie(
        "rxy_session",
        path="/",
        secure=_secure(request),
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/v1/auth/local/login")
def local_login(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    if request.app.state.mode != "local":
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    provided = request.headers.get("x-local-secret", "")
    if not _same(provided, request.app.state.secret):
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    require_write(request)
    _drop_current(request, db)
    user, org = _local_account(db)
    _set_session(response, _issue(request, db, user.id, org.tenant_id), secure=_secure(request))
    return {"user_id": user.id, "tenant_id": org.tenant_id}


@router.get("/api/v1/auth/github/start")
def github_start(
    request: Request, response: Response, db: Session = Depends(db_session)
) -> dict[str, str]:
    if not (
        request.app.state.github_client_id
        and request.app.state.github_client_secret
        and request.app.state.github_redirect_uri
    ):
        raise HTTPException(status_code=503, detail="AUTH_PROVIDER_NOT_CONFIGURED")
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state=state,
            verifier=verifier,
            browser_hash=_hash_token(request.app.state.secret, nonce),
            expires_at=datetime.now(timezone.utc) + _STATE_TTL,
        )
    )
    response.set_cookie(
        "rxy_oauth",
        nonce,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        path="/",
        max_age=int(_STATE_TTL.total_seconds()),
    )
    query = httpx.QueryParams(
        {
            "client_id": request.app.state.github_client_id,
            "redirect_uri": request.app.state.github_redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "read:user",
        }
    )
    return {
        "state": state,
        "code_challenge": challenge,
        "authorization_url": f"https://github.com/login/oauth/authorize?{query}",
    }


@router.get("/api/v1/auth/github/callback")
def github_callback(
    request: Request,
    response: Response,
    state: str,
    code: str,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    row = db.get(OAuthState, state)
    nonce = request.cookies.get("rxy_oauth", "")
    browser_ok = (
        row is not None
        and bool(nonce)
        and _same(_hash_token(request.app.state.secret, nonce), row.browser_hash)
    )
    expired = row is None or _aware(row.expires_at) <= datetime.now(timezone.utc)
    if row is None or not browser_ok or expired:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    verifier = row.verifier
    db.delete(row)
    db.flush()
    github_id = exchange_github_code(request, code, verifier)
    user, tenant_id = _github_account(db, github_id)
    if user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    _drop_current(request, db)
    _set_session(response, _issue(request, db, user.id, tenant_id), secure=_secure(request))
    return {"user_id": user.id, "tenant_id": tenant_id}


@router.get("/api/v1/me")
def me(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    return _me_body(current_record(request), db)
