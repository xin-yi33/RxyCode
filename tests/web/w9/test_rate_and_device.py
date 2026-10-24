"""W11: code-send 5-minute ceilings, register anti-batch cap, single-device lock."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.web.w9.test_auth import (  # noqa: E402
    SECRET,
    _app,
    _csrf,
    _headers,
    _login,
    _register,
    _solve_captcha,
)
from tests.web.w9.test_password_reset import _new_email  # noqa: E402

from rxycode_server.api.auth import _hash_token  # noqa: E402
from rxycode_server.persistence.models import DeviceLock  # noqa: E402


def _send_code(client: TestClient, path: str, email: str):
    return client.post(
        path,
        json={"email": email, "captcha": _solve_captcha(client)},
        headers=_headers(_csrf(client)),
    )


def _device(client: TestClient):
    return client.get("/api/v1/auth/device")


def _claim(client: TestClient):
    return client.post(
        "/api/v1/auth/device/claim",
        headers=_headers(_csrf(client)),
    )


def _session_digest(client: TestClient, secret: str) -> str:
    return _hash_token(secret, client.cookies.get("rxy_session") or "")


def test_w11_code_send_email_cap(postgres_url: str):
    """6th code send to the same email inside the 5-minute window -> 429."""
    app = _app(postgres_url)
    # _Window buckets are fixed monotonic slices — an unfrozen burst that
    # straddles a boundary silently re-allows. Freeze each limiter window so
    # the six sends share one bucket.
    limiter = app.state.auth_rate
    for window in (
        limiter.ip,
        limiter.email,
        limiter.code_email,
        limiter.code_ip,
        limiter.register_hour,
        limiter.security,
    ):
        window._window = lambda: 0  # noqa: SLF001
    client = TestClient(app)
    email = _new_email()
    codes = [
        _send_code(client, "/api/v1/auth/register/code", email).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [200] * 5
    assert codes[5] == 429


def test_w11_code_send_email_window(postgres_url: str):
    """The 5-minute email bucket caps independently of the 60s buckets:
    four sends already banked -> the real 6th is refused."""
    app = _app(postgres_url)
    limiter = app.state.auth_rate
    email = _new_email()
    for _ in range(4):
        assert limiter.code_email.hit(f"register-code:email:{email}")
    client = TestClient(app)
    ok = _send_code(client, "/api/v1/auth/register/code", email)
    assert ok.status_code == 200  # 5th inside the 5-min window
    blocked = _send_code(client, "/api/v1/auth/register/code", email)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"


def test_w11_code_send_ip_window(postgres_url: str):
    """Per-IP 15 sends / 5min on the code paths — a shared ceiling across
    emails (14 banked hits + one honest send fill it)."""
    app = _app(postgres_url)
    limiter = app.state.auth_rate
    for _ in range(14):
        assert limiter.code_ip.hit("login-code:ip:testclient")
    client = TestClient(app)
    ok = _send_code(client, "/api/v1/auth/login/code", _new_email())
    assert ok.status_code == 200  # 15th — still inside the ceiling
    blocked = _send_code(client, "/api/v1/auth/login/code", _new_email())
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"


def test_w11_register_hourly_ip_cap(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """Max 5 successful registrations per IP per hour — distinct emails so
    only the hourly bucket can refuse the 6th."""
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    codes = [
        _register(client, _new_email(), "password-123").status_code
        for _ in range(6)
    ]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429
    # A failed attempt must NOT count toward the hourly five.
    assert app.state.auth_rate.register_hour.count(
        "register:ip:testclient"
    ) == 5


def test_w11_device_lock_takeover(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """One account, one active device: login claims the lock for the new
    session; the displaced session keeps auth but data-plane -> 409."""
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    a = TestClient(app)
    email = _new_email()
    registered = _register(a, email, "password-123")
    assert registered.status_code == 201
    # The register session holds the lock immediately.
    assert _device(a).json() == {"status": "active"}
    assert a.get("/api/v1/projects").status_code == 200

    # Second session logs in — the login claims the lock for session B.
    b = TestClient(app)
    assert _login(b, email, "password-123").status_code == 200
    assert _device(b).json() == {"status": "active"}
    assert _device(a).json() == {"status": "held_elsewhere"}
    assert b.get("/api/v1/projects").status_code == 200

    # Session A is NOT revoked (auto-login still works) — but the data
    # plane refuses it. /api/v1/auth/* and /api/v1/me stay reachable.
    assert a.get("/api/v1/me").status_code == 200
    blocked = a.get("/api/v1/projects")
    assert blocked.status_code == 409
    assert blocked.json() == {"code": "DEVICE_IN_USE"}

    # Takeover back to A: claim is exempt from the gate, then A works and B
    # is the displaced one.
    assert _claim(a).json() == {"claimed": True}
    assert a.get("/api/v1/projects").status_code == 200
    assert b.get("/api/v1/projects").status_code == 409
    assert _device(b).json() == {"status": "held_elsewhere"}


def test_w11_device_lock_expiry(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """A lock idle past the 10-minute TTL is implicitly released: status
    reads `none` and the next request auto-claims it — a dead device can
    never strand the account."""
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    a = TestClient(app)
    email = _new_email()
    registered = _register(a, email, "password-123")
    assert registered.status_code == 201
    user_id = registered.json()["user"]["id"]

    b = TestClient(app)
    assert _login(b, email, "password-123").status_code == 200
    assert b.get("/api/v1/projects").status_code == 200

    # Age the holder's last_seen past the TTL — holder B went dark.
    stale = datetime.now(timezone.utc) - timedelta(minutes=11)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(DeviceLock)
            .where(DeviceLock.user_id == user_id)
            .values(last_seen_at=stale)
        )
        db.commit()
    engine.dispose()

    assert _device(a).json() == {"status": "none"}
    # A's data-plane request auto-claims the stale lock instead of 409ing.
    assert a.get("/api/v1/projects").status_code == 200
    assert _device(a).json() == {"status": "active"}
    with Session(create_engine(postgres_url)) as db:
        lock = db.get(DeviceLock, user_id)
        assert lock is not None
        assert lock.token_hash == _session_digest(a, SECRET)
    # ...and the formerly-live B is now the displaced session.
    assert b.get("/api/v1/projects").status_code == 409
    assert _device(b).json() == {"status": "held_elsewhere"}
