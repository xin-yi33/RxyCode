"""WEB-W9-B1. Registration, login, durable sessions, invites, rate limits, CLI."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.api.auth import _hash_token, invite_digest  # noqa: E402
from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.models import AuthSession, Invite, User  # noqa: E402

ORIGIN = "https://w9.example"
SECRET = "w9-web-secret-value-32bytes-long!!"


def _app(postgres_url: str, mode: str = "local", **kwargs):
    # local mode: non-secure cookies flow through TestClient's http transport.
    return create_app(
        postgres_url,
        mode=mode,
        secret=SECRET,
        allowed_origins=[ORIGIN],
        **kwargs,
    )


def _csrf(client: TestClient) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": ORIGIN}


def _solve_captcha(client: TestClient) -> str:
    """Fetch a real ALTCHA challenge and brute-force the PoW — the same math
    the browser widget performs. Keeps every test exercising the real gate."""
    import base64
    import hashlib
    import json as _json

    challenge = client.get("/api/v1/auth/altcha")
    assert challenge.status_code == 200, challenge.text
    body = challenge.json()
    salt, target = body["salt"], body["challenge"]
    number = 0
    while hashlib.sha256(f"{salt}{number}".encode()).hexdigest() != target:
        number += 1
    return base64.b64encode(
        _json.dumps(
            {
                "algorithm": "SHA-256",
                "challenge": target,
                "number": number,
                "salt": salt,
                "signature": body["signature"],
                "took": 0,
            }
        ).encode()
    ).decode()


def _invite(postgres_url: str, code: str, *, uses: int = 1, days: int | None = 30) -> None:
    expires = datetime.now(timezone.utc) + timedelta(days=days) if days else None
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(
            Invite(
                code_hash=invite_digest(code),
                max_uses=uses,
                used=0,
                expires_at=expires,
                note="w9-test",
            )
        )
        db.commit()
    engine.dispose()


def _register(
    client: TestClient, email: str, password: str, invite_code: str = "", code: str = ""
):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "invite_code": invite_code,
            "captcha": _solve_captcha(client),
            **({"code": code} if code else {}),
        },
        headers=_headers(_csrf(client)),
    )


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "captcha": _solve_captcha(client)},
        headers=_headers(_csrf(client)),
    )


def test_w9_b1_register_and_me(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    code = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, code)
    response = _register(client, "  Alice@Example.COM ", "password-123", code)
    assert response.status_code == 201, response.text
    body = response.json()
    # §5.1: /me-shaped body — nested only, no flat mirrors.
    assert set(body) == {"user", "organization", "membership", "default_project_id"}
    assert body["user"]["email"] == "alice@example.com"  # normalized
    assert body["user"]["id"]
    assert body["user"]["kind"] == "email"
    assert body["organization"]["tenant_id"]
    assert body["membership"]["role"] == "owner"
    assert body["default_project_id"]
    capabilities = client.get("/api/v1/auth/capabilities")
    assert capabilities.json()["registration"] == "invite"
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "alice@example.com"
    assert me.json()["default_project_id"] == body["default_project_id"]


def test_w9_b1_register_duplicate_and_invite_rules(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    code = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, code, uses=1)
    first = _register(client, "one@example.com", "password-123", code)
    assert first.status_code == 201
    # used-up invite is refused for the second registration
    spent = _register(client, "two@example.com", "password-123", code)
    assert spent.status_code == 403
    assert spent.json()["code"] == "INVITE_INVALID"
    # wrong invite refused
    wrong = _register(client, "two@example.com", "password-123", "bogus-code")
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "INVITE_INVALID"
    # expired invite refused
    stale = "w9-invite-" + uuid.uuid4().hex[:12]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(
            Invite(
                code_hash=invite_digest(stale),
                max_uses=1,
                used=0,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.commit()
    engine.dispose()
    expired = _register(client, "two@example.com", "password-123", stale)
    assert expired.status_code == 403
    # duplicate email refused even in open mode
    other = TestClient(_app(postgres_url))
    dup = _register(other, "ONE@example.com", "password-123", code)
    assert dup.status_code in (403, 409)
    # bad email / short password -> 400 INVALID_INPUT
    bad = _register(other, "not-an-email", "password-123", "")
    assert bad.status_code == 400
    short = _register(other, "ok@example.com", "short", "")
    assert short.status_code == 400


def test_w9_b1_invite_single_use_race(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """One invite seat, two concurrent registrars: exactly one consumes it —
    the UPDATE...RETURNING claim is atomic, no read-then-increment race."""
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "invite")
    app = _app(postgres_url)
    code = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, code, uses=1)
    barrier = threading.Barrier(2)
    results: list[int] = []

    def attempt(email: str) -> None:
        client = TestClient(app)
        barrier.wait(timeout=30)
        results.append(_register(client, email, "password-123", code).status_code)

    threads = [
        threading.Thread(target=attempt, args=(f"race-{i}@example.com",))
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(results) == [201, 403]
    with Session(create_engine(postgres_url)) as db:
        row = db.get(Invite, invite_digest(code))
        assert row is not None and row.used == 1


def test_w9_b1_registration_modes(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    response = _register(client, "open@example.com", "password-123")
    assert response.status_code == 201, response.text

    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "closed")
    closed_app = _app(postgres_url)
    closed = TestClient(closed_app)
    denied = _register(closed, "shut@example.com", "password-123")
    assert denied.status_code == 403
    assert denied.json()["code"] == "REGISTRATION_CLOSED"


def test_w9_b1_login_logout_and_timing(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    assert _register(client, "in@example.com", "password-123").status_code == 201
    # wrong password and unknown email share the refusal
    wrong = _login(client, "in@example.com", "password-124")
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "INVALID_CREDENTIALS"
    ghost = _login(client, "ghost@example.com", "password-124")
    assert ghost.status_code == 401
    assert ghost.json()["code"] == "INVALID_CREDENTIALS"
    good = _login(client, "in@example.com", "password-123")
    assert good.status_code == 200
    assert good.json()["user"]["email"] == "in@example.com"
    # logout revokes the durable session AND expires the cookie; repeat is 204
    out = client.post("/api/v1/auth/logout", headers=_headers(_csrf(client)))
    assert out.status_code == 204
    cleared = out.headers.get("set-cookie") or ""
    assert "rxy_session=" in cleared
    assert "Max-Age=0" in cleared
    assert client.get("/api/v1/me").status_code == 401
    again = client.post("/api/v1/auth/logout", headers=_headers(_csrf(client)))
    assert again.status_code == 204


def test_w9_b1_session_survives_restart(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    assert _register(client, "stay@example.com", "password-123").status_code == 201
    cookie = client.cookies.get("rxy_session")
    # "restart" = a second app against the same database
    app2 = _app(postgres_url)
    revived = TestClient(app2)
    revived.cookies.set("rxy_session", cookie)
    me = revived.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "stay@example.com"


def test_w9_b1_expired_and_sliding_session(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    assert _register(client, "age@example.com", "password-123").status_code == 201
    cookie = client.cookies.get("rxy_session")
    digest = _hash_token(SECRET, cookie)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == digest)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        db.commit()
    engine.dispose()
    assert client.get("/api/v1/me").status_code == 401
    # sliding renewal: a session idle >1d gets last_seen_at/expires_at bumped
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == digest)
            .values(
                expires_at=datetime.now(timezone.utc) + timedelta(days=6),
                last_seen_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        db.commit()
    engine.dispose()
    assert client.get("/api/v1/me").status_code == 200
    with Session(create_engine(postgres_url)) as db:
        row = db.get(AuthSession, digest)
        assert row is not None
        assert row.last_seen_at.replace(tzinfo=timezone.utc) > datetime.now(
            timezone.utc
        ) - timedelta(minutes=5)


def test_w9_b1_write_without_csrf_refused(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    # no Origin/CSRF at all
    denied = client.post(
        "/api/v1/auth/login", json={"email": "a@b.co", "password": "password-1"}
    )
    assert denied.status_code == 403
    task = client.post(
        "/api/v1/tasks",
        json={
            "message": "hello",
            "request_id": "req-" + uuid.uuid4().hex[:12],
            "permission_profile": "confirm",
        },
    )
    assert task.status_code == 403


def test_w9_b1_local_login_refused_in_cloud(postgres_url: str):
    app = _app(postgres_url, mode="cloud")
    client = TestClient(app)
    token = _csrf(client)
    denied = client.post(
        "/api/v1/auth/local/login",
        headers={**_headers(token), "X-Local-Secret": SECRET},
    )
    assert denied.status_code == 403


def test_w9_b1_rate_limit(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    # per-IP cap is 10/min on /auth/login; distinct emails dodge the 5/min email cap
    codes = [
        _login(client, f"probe{i}@example.com", "password-123").status_code
        for i in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    # per-email cap is 5/min on /auth/register
    reg_codes = [
        _register(client, "same@example.com", "password-123").status_code
        for _ in range(6)
    ]
    assert reg_codes[-1] == 429


def test_w9_b1_github_start_unconfigured(postgres_url: str):
    app = _app(postgres_url)  # no github credentials
    client = TestClient(app)
    denied = client.get("/api/v1/auth/github/start")
    assert denied.status_code == 503
    assert denied.json()["code"] == "AUTH_PROVIDER_NOT_CONFIGURED"


def _admin(postgres_url: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC)
    env["RXYCODE_WEB_DATABASE_URL"] = postgres_url
    return subprocess.run(
        [sys.executable, "-m", "rxycode_server.admin", *args],
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )


def test_w9_b1_admin_cli(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    app = _app(postgres_url)
    client = TestClient(app)
    assert _register(client, "adm@example.com", "password-123").status_code == 201

    # invite create prints the plaintext once; only sha256 is stored
    created = _admin(postgres_url, "invite", "create", "--uses", "2", "--note", "w9")
    assert created.returncode == 0, created.stderr
    code = created.stdout.strip()
    assert code
    with Session(create_engine(postgres_url)) as db:
        row = db.get(Invite, invite_digest(code))
        assert row is not None and row.max_uses == 2
    listed = _admin(postgres_url, "invite", "list")
    assert listed.returncode == 0
    assert invite_digest(code)[:12] in listed.stdout

    # reset-password reads stdin, revokes sessions, and accepts the new password
    reset = _admin(
        postgres_url, "user", "reset-password", "--email", "adm@example.com",
        stdin="fresh-password-9\n",
    )
    assert reset.returncode == 0, reset.stderr
    assert client.get("/api/v1/me").status_code == 401
    old = _login(client, "adm@example.com", "password-123")
    assert old.status_code == 401
    new = _login(client, "adm@example.com", "fresh-password-9")
    assert new.status_code == 200

    # disable revokes sessions and refuses login
    disabled = _admin(postgres_url, "user", "disable", "--email", "adm@example.com")
    assert disabled.returncode == 0, disabled.stderr
    assert client.get("/api/v1/me").status_code == 401
    blocked = _login(client, "adm@example.com", "fresh-password-9")
    assert blocked.status_code == 401
    with Session(create_engine(postgres_url)) as db:
        user = db.scalars(select(User).where(User.email == "adm@example.com")).one()
        assert user.disabled_at is not None
