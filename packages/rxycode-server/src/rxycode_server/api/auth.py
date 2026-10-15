"""GitHub OAuth with PKCE, local login, and the cookie session."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.persistence.models import Membership, Organization, User

router = APIRouter()
_SESSION_TTL = 12 * 60 * 60
_STATE_TTL = 10 * 60


@dataclass
class OAuthState:
    verifier: str
    created: float


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


def current_record(request: Request) -> AuthRecord:
    raw = request.cookies.get("rxy_session", "")
    if not raw:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    record = request.app.state.sessions.get(_hash_token(request.app.state.secret, raw))
    if record is None or time.monotonic() - record.created > _SESSION_TTL:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    return record


def _drop_current(request: Request) -> None:
    raw = request.cookies.get("rxy_session", "")
    if not raw:
        return
    request.app.state.sessions.pop(_hash_token(request.app.state.secret, raw), None)


def _issue(request: Request, user_id: str, tenant_id: str) -> str:
    token = secrets.token_urlsafe(32)
    request.app.state.sessions[_hash_token(request.app.state.secret, token)] = AuthRecord(
        user_id=user_id,
        tenant_id=tenant_id,
        created=time.monotonic(),
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
        max_age=_SESSION_TTL,
    )


def _local_account(db: Session) -> tuple[User, Organization]:
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


@router.post("/api/v1/auth/local/login")
def local_login(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    require_write(request)
    _drop_current(request)
    user, org = _local_account(db)
    _set_session(response, _issue(request, user.id, org.tenant_id), secure=_secure(request))
    return {"user_id": user.id, "tenant_id": org.tenant_id}


@router.get("/api/v1/auth/github/start")
def github_start(request: Request) -> dict[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    request.app.state.oauth_states[state] = OAuthState(verifier=verifier, created=time.monotonic())
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
    record = request.app.state.oauth_states.pop(state, None)
    if record is None or time.monotonic() - record.created > _STATE_TTL:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    github_id = exchange_github_code(request, code, record.verifier)
    _drop_current(request)
    user, tenant_id = _github_account(db, github_id)
    _set_session(response, _issue(request, user.id, tenant_id), secure=_secure(request))
    return {"user_id": user.id, "tenant_id": tenant_id}


@router.get("/api/v1/me")
def me(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    record = current_record(request)
    user = db.get(User, record.user_id)
    org = db.scalars(select(Organization).where(Organization.tenant_id == record.tenant_id)).one()
    role = db.scalars(
        select(Membership.role).where(
            Membership.user_id == record.user_id,
            Membership.tenant_id == record.tenant_id,
        )
    ).one()
    if user is None:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    return {
        "user": {"id": user.id, "kind": user.kind, "github_id": user.github_id},
        "organization": {"id": org.id, "tenant_id": org.tenant_id},
        "membership": {"role": role},
    }
