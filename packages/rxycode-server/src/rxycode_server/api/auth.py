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
import re
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

from rxycode_server.altcha import _ReplayRegistry, create_challenge, verify_payload
from rxycode_server.api.client_ip import client_ip
from rxycode_server.persistence.models import (
    AuthSession,
    DeviceLock,
    EmailCode,
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
_CODE_TTL = timedelta(minutes=15)
_CODE_MAX_ATTEMPTS = 5
_DEVICE_LOCK_TTL = timedelta(minutes=10)
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

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.buckets: dict[tuple[str, int], int] = {}

    def _window(self) -> int:
        return int(time.monotonic()) // self.window_seconds

    def count(self, key: str) -> int:
        """Hits so far in the current window — no increment (success-only
        counters peek here and ``hit`` once the counted event lands)."""
        return self.buckets.get((key, self._window()), 0)

    def hit(self, key: str) -> bool:
        window = self._window()
        bucket = (key, window)
        seen = self.buckets.get(bucket, 0)
        if seen >= self.limit:
            return False
        self.buckets[bucket] = seen + 1
        if len(self.buckets) > 4096:
            self.buckets = {k: v for k, v in self.buckets.items() if k[1] >= window - 1}
        return True


class AuthRateLimit:
    """Per-IP 10/min + per-email 5/min on /auth/register and /auth/login;
    per-email 5/5min + per-IP 15/5min on the code-send paths; per-IP
    5 successful registrations per hour."""

    def __init__(self) -> None:
        self.ip = _Window(10)
        self.email = _Window(5)
        self.code_email = _Window(5, window_seconds=300)
        self.code_ip = _Window(15, window_seconds=300)
        self.register_hour = _Window(5, window_seconds=3600)
        self.security = _Window(5)

    def hit(self, key: str) -> bool:
        """Security routes still call this after the windowed counters split out."""
        return self.security.hit(key)

    def check(self, route: str, ip: str, email: str) -> None:
        if not self.ip.hit(f"{route}:ip:{ip}") or not self.email.hit(f"{route}:email:{email}"):
            raise HTTPException(status_code=429, detail="RATE_LIMITED")

    def check_code(self, route: str, ip: str, email: str) -> None:
        """Send-side ceiling for the three code paths: a 5-minute window so a
        burst under the per-minute caps still cannot mailbomb one address."""
        if not self.code_email.hit(f"{route}:email:{email}") or not self.code_ip.hit(
            f"{route}:ip:{ip}"
        ):
            raise HTTPException(status_code=429, detail="RATE_LIMITED")

    def check_register_hour(self, ip: str) -> None:
        """Anti-batch gate: refuse before invite/user work once this IP already
        produced ``limit`` successful registrations in the window."""
        if self.register_hour.count(f"register:ip:{ip}") >= self.register_hour.limit:
            raise HTTPException(status_code=429, detail="RATE_LIMITED")

    def record_register(self, ip: str) -> None:
        """Count a committed registration — failed attempts never reach here."""
        self.register_hour.hit(f"register:ip:{ip}")


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


def _claim_device(db: Session, user_id: str, token_hash: str, now: datetime) -> None:
    """Unconditional takeover: ``user_id``'s lock row now names ``token_hash``.
    Callers commit it in the same transaction as the session row."""
    lock = db.get(DeviceLock, user_id)
    if lock is None:
        db.add(
            DeviceLock(
                user_id=user_id,
                token_hash=token_hash,
                created_at=now,
                last_seen_at=now,
            )
        )
    else:
        lock.token_hash = token_hash
        lock.last_seen_at = now


def _lock_expired(lock: DeviceLock, now: datetime) -> bool:
    return _aware(lock.last_seen_at) <= now - _DEVICE_LOCK_TTL


def _device_gate(request: Request, record: AuthRecord, raw: str) -> None:
    """Single active device: an authenticated request whose session is NOT the
    lock holder gets 409 DEVICE_IN_USE — unless the holder went idle past the
    TTL, in which case the lock is provably stale and this request auto-claims
    it (a dead device can never strand the account). The holder's requests
    refresh ``last_seen_at`` — that one UPDATE is the lock's keepalive.

    ``/api/v1/auth/*`` and ``/api/v1/me`` stay exempt: the displaced device
    must still reach status/claim/logout, and a lock row only exists once an
    ``engine``-backed login issued it (in-memory session mode has none)."""
    path = request.url.path
    if path == "/api/v1/me" or path == "/api/v1/auth" or path.startswith("/api/v1/auth/"):
        return
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return
    digest = _hash_token(request.app.state.secret, raw)
    # A dict-injected session has no users row. Writing a device lock would
    # violate device_locks_user_id_fkey. Production never sets this dict.
    if getattr(request.app.state, "sessions", {}).get(digest) is not None:
        return
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        lock = db.get(DeviceLock, record.user_id)
        if lock is not None and lock.token_hash != digest and not _lock_expired(lock, now):
            raise HTTPException(status_code=409, detail="DEVICE_IN_USE")
        if lock is None:
            db.add(
                DeviceLock(
                    user_id=record.user_id,
                    token_hash=digest,
                    created_at=now,
                    last_seen_at=now,
                )
            )
        else:
            lock.token_hash = digest
            lock.last_seen_at = now
        db.commit()


def current_record(request: Request) -> AuthRecord:
    raw = request.cookies.get("rxy_session", "")
    if not raw:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    record = _lookup_session(request.app, raw)
    if record is None:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    _device_gate(request, record, raw)
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
    ip = ""
    try:
        from rxycode_server.api.client_ip import client_ip

        ip = client_ip(request)
    except Exception:
        ip = ""
    db.add(
        AuthSession(
            token_hash=digest,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=now,
            expires_at=now + _SESSION_TTL,
            last_seen_at=now,
            device_label=(request.headers.get("user-agent") or "")[:128],
            ip_hint=ip[:64],
        )
    )
    # The new session takes the single-device lock in the same commit.
    _claim_device(db, user_id, digest, now)
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


def _require_captcha(request: Request, payload: dict) -> None:
    """ALTCHA proof-of-work gate — cheap to solve once, expensive to spam."""
    registry = getattr(request.app.state, "altcha_registry", None)
    if registry is None:
        registry = _ReplayRegistry()
        request.app.state.altcha_registry = registry
    if not verify_payload(payload.get("captcha"), request.app.state.secret, registry):
        raise HTTPException(status_code=400, detail="CAPTCHA_INVALID")


def _code_digest(secret: str, purpose: str, email: str, code: str) -> str:
    return _hash_token(secret, f"{purpose}:{email}:{code}")


def _burn_codes(db: Session, purpose: str, email: str) -> None:
    """Only the newest code works: spend outstanding ones for this pair."""
    now = datetime.now(timezone.utc)
    db.execute(
        update(EmailCode)
        .where(
            EmailCode.purpose == purpose,
            EmailCode.email == email,
            EmailCode.used_at.is_(None),
        )
        .values(used_at=now)
    )


def _mint_code(request: Request, db: Session, purpose: str, email: str, user_id: str | None) -> str:
    _burn_codes(db, purpose, email)
    now = datetime.now(timezone.utc)
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        EmailCode(
            code_hash=_code_digest(request.app.state.secret, purpose, email, code),
            purpose=purpose,
            email=email,
            user_id=user_id,
            created_at=now,
            expires_at=now + _CODE_TTL,
        )
    )
    db.flush()
    return code


def _deliver_code(request: Request, email: str, code: str, subject: str) -> str | None:
    """Send/log/hand back the code. Returns the delivery channel used."""
    state = request.app.state
    smtp_url = str(getattr(state, "smtp_url", "") or "")
    if smtp_url:
        from rxycode_server.mailer import send_mail

        if send_mail(
            smtp_url,
            to=email,
            subject=subject,
            sender=str(getattr(state, "smtp_from", "") or ""),
            body=(
                f"你的验证码：{code}\n\n"
                "15 分钟内有效，输错 5 次失效。如果不是你本人操作，忽略本邮件即可。"
            ),
        ):
            return "smtp"
    if state.mode == "local":
        return "inline"
    if getattr(state, "reset_operator_log", False):
        # Operator outbox — register/login pages accept the code directly.
        log.warning("verification code for %s (operator outbox): %s", email, code)
        return "operator-log"
    return None


def _code_attempts(request: Request) -> dict:
    attempts = getattr(request.app.state, "reset_code_attempts", None)
    if attempts is None:
        attempts = {}
        request.app.state.reset_code_attempts = attempts
    return attempts


def _redeem_code(
    request: Request,
    db: Session,
    purpose: str,
    email: str,
    code: str,
    detail: str = "CODE_INVALID",
) -> EmailCode:
    """Verify a 6-digit code: fresh, unspent, unexpired — else burn one of
    the five attempts and (at the ceiling) burn the outstanding code itself."""
    if not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    attempts = _code_attempts(request)
    key = f"{purpose}:{email}"
    if attempts.get(key, 0) >= _CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail=detail)
    now = datetime.now(timezone.utc)
    row = db.get(EmailCode, _code_digest(request.app.state.secret, purpose, email, code))
    if row is None or row.used_at is not None or _aware(row.expires_at) <= now:
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] >= _CODE_MAX_ATTEMPTS:
            _burn_codes(db, purpose, email)
        raise HTTPException(status_code=400, detail=detail)
    row.used_at = now
    attempts.pop(key, None)
    return row


def _local_account(db: Session) -> tuple[User, Organization]:
    """Local mode has one user. A later login keeps that user and tenant."""
    user = db.scalars(select(User).where(User.kind == "local")).one_or_none()
    if user is not None:
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one_or_none()
        if tenant_id is None:
            org = Organization(id=uuid.uuid4().hex, tenant_id=uuid.uuid4().hex)
            db.add(org)
            db.add(
                Membership(
                    id=uuid.uuid4().hex,
                    tenant_id=org.tenant_id,
                    user_id=user.id,
                    role="owner",
                )
            )
            db.flush()
            return user, org
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
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one()
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
        is_default=True,
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


def _delivery_channel(state) -> str:
    """How a mailed code/link can reach the user on this deployment."""
    if getattr(state, "smtp_url", ""):
        return "smtp"
    if state.mode == "local":
        return "inline"
    if getattr(state, "reset_operator_log", False):
        return "operator-log"
    return "none"


def _capabilities(request: Request) -> dict[str, object]:
    state = request.app.state
    reset_delivery = _delivery_channel(state)
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
        # 6-digit email codes (register verify + code login) are offered only
        # where a code can actually be delivered; ALTCHA proof-of-work gates
        # every auth endpoint.
        "code_delivery": reset_delivery if reset_delivery in ("smtp", "operator-log") else "none",
        "captcha": "altcha",
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
    ip = client_ip(request)
    if limiter is not None:
        limiter.check("register", ip, email)
        # Anti-batch: at the hourly ceiling, refuse before an invite seat or
        # a user row is touched — only committed registrations count.
        limiter.check_register_hour(ip)
    _check_email(email)
    password = str(payload.get("password") or "")
    if not 8 <= len(password) <= 128:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    _require_captcha(request, payload)
    # Email proof is required whenever the deploy can actually deliver a code
    # (smtp or the operator outbox). local/inline and no-channel deploys keep
    # the bare email+password form.
    if _delivery_channel(request.app.state) in ("smtp", "operator-log"):
        code = str(payload.get("code") or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="CODE_REQUIRED")
        _redeem_code(request, db, "register", email, code)
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
    db.add(Membership(id=uuid.uuid4().hex, tenant_id=tenant_id, user_id=user.id, role="owner"))
    try:
        user.default_project_id = _ensure_default_project(db, tenant_id)
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="EMAIL_TAKEN") from None
    if limiter is not None:
        # Only now does the attempt count — the user row survived flush.
        limiter.record_register(ip)
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
        limiter.check("login", client_ip(request), email)
    _require_captcha(request, payload)
    user = db.scalars(select(User).where(User.email == email).limit(1)).first()
    code = str(payload.get("code") or "").strip()
    if code:
        # Code login — same error shape as a wrong password.
        if user is None or user.disabled_at is not None:
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
        try:
            _redeem_code(request, db, "login", email, code, detail="INVALID_CREDENTIALS")
        except HTTPException:
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS") from None
    else:
        # Always run one scrypt so unknown-email and wrong-password look alike.
        stored = user.password_hash if user is not None and user.password_hash else _DUMMY_HASH
        if user is None or not verify_password(str(payload.get("password") or ""), stored):
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    if user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    tenant_id = _tenant_for(db, user.id)
    # MFA gate: password verified, but an enabled factor means no cookie yet —
    # the client completes the challenge before _issue runs.
    from rxycode_server.api.security import (
        issue_mfa_challenge,
        mfa_required_for,
        record_security_event,
    )

    methods = mfa_required_for(db, user.id)
    if methods:
        challenge_id = issue_mfa_challenge(db, user.id, tenant_id)
        record_security_event(
            db,
            user_id=user.id,
            tenant_id=tenant_id,
            type="mfa_challenge_issued",
            result="ok",
            device_label=(request.headers.get("user-agent") or "")[:128],
        )
        db.flush()
        return {
            "mfa_required": True,
            "challenge_id": challenge_id,
            "allowed_methods": methods + ["recovery_code"],
        }
    _drop_current(request, db)
    _set_session(response, _issue(request, db, user.id, tenant_id), secure=_secure(request))
    record_security_event(
        db,
        user_id=user.id,
        tenant_id=tenant_id,
        type="login",
        result="ok",
        device_label=(request.headers.get("user-agent") or "")[:128],
    )
    db.flush()
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
    ip = client_ip(request)
    if limiter is not None:
        limiter.check("forgot", ip, email)
        limiter.check_code("forgot", ip, email)
    _require_captcha(request, payload)
    user = db.scalars(select(User).where(User.email == email).limit(1)).first()
    body: dict[str, object] = {"ok": True}
    if (
        user is None
        or user.kind != "email"
        or user.disabled_at is not None
        or not user.password_hash
    ):
        return body
    now = datetime.now(timezone.utc)
    # Only the newest link/code works: outstanding tokens for this user are
    # spent.
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=now)
    )
    smtp_url = str(getattr(request.app.state, "smtp_url", "") or "")
    if smtp_url:
        # SMTP deployments get a 6-digit code (typed on the forgot page);
        # the digest is purpose+email-scoped so a guessed code fits nothing
        # else.
        code = _mint_code(request, db, "reset", email, user.id)
        from rxycode_server.mailer import send_mail

        if send_mail(
            smtp_url,
            to=email,
            subject="RxyCode 密码重置验证码",
            sender=str(getattr(request.app.state, "smtp_from", "") or ""),
            body=(
                f"你的密码重置验证码：{code}\n\n"
                "15 分钟内有效，输错 5 次失效。如果不是你本人操作，忽略本邮件即可。"
            ),
        ):
            body["delivery"] = "smtp"
            return body
        if getattr(request.app.state, "reset_operator_log", False):
            # SMTP path down — the code has no redeeming UI in operator-log
            # mode, so burn it and log a standard link instead.
            _burn_codes(db, "reset", email)
            token = secrets.token_urlsafe(32)
            reset_url = f"{request.headers.get('origin', '')}/reset?token={token}"
            db.add(
                PasswordReset(
                    token_hash=_hash_token(request.app.state.secret, token),
                    user_id=user.id,
                    created_at=now,
                    expires_at=now + _RESET_TTL,
                )
            )
            db.flush()
            log.warning(
                "password reset link for %s (SMTP failed, operator outbox): %s",
                email,
                reset_url,
            )
            body["delivery"] = "operator-log"
        return body

    token = secrets.token_urlsafe(32)
    reset_url = f"{request.headers.get('origin', '')}/reset?token={token}"
    db.add(
        PasswordReset(
            token_hash=_hash_token(request.app.state.secret, token),
            user_id=user.id,
            created_at=now,
            expires_at=now + _RESET_TTL,
        )
    )
    db.flush()
    if request.app.state.mode == "local":
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


def _reset_with_code(request: Request, payload: dict, db: Session) -> dict[str, object]:
    """Redeem an emailed 6-digit code. The stored digest is scoped to the
    purpose+email (``reset:{email}:{code}``) and repeated wrong codes burn the
    outstanding code — a 10^6 space stays safe at this ceiling."""
    email = _normalize_email(str(payload.get("email") or ""))
    code = str(payload.get("code") or "").strip()
    password = str(payload.get("password") or "")
    if not email or not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if not 8 <= len(password) <= 128:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check("reset-code", client_ip(request), email)
    user = db.scalars(select(User).where(User.email == email).limit(1)).first()
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=400, detail="RESET_INVALID")
    _redeem_code(request, db, "reset", email, code, detail="RESET_INVALID")
    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(password)
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return {"ok": True}


@router.post("/api/v1/auth/reset")
def reset_password(
    request: Request,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Redeem a reset token: sets the password and revokes every session."""
    require_write(request)
    if str(payload.get("code") or "").strip():
        return _reset_with_code(request, payload, db)
    token = str(payload.get("token") or "")
    password = str(payload.get("password") or "")
    limiter = getattr(request.app.state, "auth_rate", None)
    if limiter is not None:
        limiter.check(
            "reset",
            client_ip(request),
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


@router.get("/api/v1/auth/altcha")
def altcha_challenge(request: Request) -> dict[str, object]:
    """Fresh signed PoW challenge for the ALTCHA widget (no side effects)."""
    return create_challenge(request.app.state.secret)


@router.post("/api/v1/auth/register/code")
def register_code(
    request: Request,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Send a 6-digit register-verify code. Always 200 — never reveals
    whether the email is already registered."""
    require_write(request)
    email = _normalize_email(str(payload.get("email") or ""))
    limiter = getattr(request.app.state, "auth_rate", None)
    ip = client_ip(request)
    if limiter is not None:
        limiter.check("register-code", ip, email)
        limiter.check_code("register-code", ip, email)
    _check_email(email)
    _require_captcha(request, payload)
    channel = _delivery_channel(request.app.state)
    body: dict[str, object] = {"ok": True, "delivery": channel}
    taken = db.scalars(select(User.id).where(User.email == email).limit(1)).first()
    if taken or channel == "none":
        return body
    code = _mint_code(request, db, "register", email, None)
    body["delivery"] = _deliver_code(request, email, code, "RxyCode 注册验证码") or channel
    if body["delivery"] == "inline":
        body["dev_code"] = code
    return body


@router.post("/api/v1/auth/login/code")
def login_code(
    request: Request,
    payload: dict,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Send a 6-digit login code. Always 200 — never reveals whether the
    email exists."""
    require_write(request)
    email = _normalize_email(str(payload.get("email") or ""))
    limiter = getattr(request.app.state, "auth_rate", None)
    ip = client_ip(request)
    if limiter is not None:
        limiter.check("login-code", ip, email)
        limiter.check_code("login-code", ip, email)
    _check_email(email)
    _require_captcha(request, payload)
    channel = _delivery_channel(request.app.state)
    body: dict[str, object] = {"ok": True, "delivery": channel}
    user = db.scalars(select(User).where(User.email == email).limit(1)).first()
    if user is None or user.disabled_at is not None or user.kind != "email" or channel == "none":
        return body
    code = _mint_code(request, db, "login", email, user.id)
    body["delivery"] = _deliver_code(request, email, code, "RxyCode 登录验证码") or channel
    if body["delivery"] == "inline":
        body["dev_code"] = code
    return body


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


def _session_digest(request: Request) -> str:
    return _hash_token(request.app.state.secret, request.cookies.get("rxy_session", ""))


@router.get("/api/v1/auth/device")
def device_status(request: Request, db: Session = Depends(db_session)) -> dict[str, str]:
    """The caller's lock view: ``active`` (this session holds it),
    ``held_elsewhere`` (a live other session holds it), ``none`` (no row or
    the holder went idle past the TTL — the lock is free for the taking)."""
    record = current_record(request)
    digest = _session_digest(request)
    now = datetime.now(timezone.utc)
    lock = db.get(DeviceLock, record.user_id)
    if lock is None or _lock_expired(lock, now):
        return {"status": "none"}
    if lock.token_hash != digest:
        return {"status": "held_elsewhere"}
    # Holder polling status is liveness — same refresh the data-plane gate does.
    lock.last_seen_at = now
    return {"status": "active"}


@router.post("/api/v1/auth/device/claim")
def device_claim(request: Request, db: Session = Depends(db_session)) -> dict[str, bool]:
    """Takeover: unconditionally re-points the lock at the caller's session."""
    require_write(request)
    record = current_record(request)
    _claim_device(db, record.user_id, _session_digest(request), datetime.now(timezone.utc))
    return {"claimed": True}
