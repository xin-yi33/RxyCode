"""WEB-W9-A1. Password reset: token lifecycle, delivery modes, session revoke."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from tests.web.w9.test_auth import _app, _csrf, _headers, _invite, _login, _register

from rxycode_server.persistence.models import PasswordReset  # noqa: E402


def _forgot(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/forgot",
        json={"email": email},
        headers=_headers(_csrf(client)),
    )


def _reset(client: TestClient, token: str, password: str):
    return client.post(
        "/api/v1/auth/reset",
        json={"token": token, "password": password},
        headers=_headers(_csrf(client)),
    )


def _token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def _register_user(client: TestClient, postgres_url: str) -> tuple[str, str]:
    email = f"reset-{uuid.uuid4().hex[:10]}@w9.example"
    code = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, code)
    response = _register(client, email, "old-password-1", code)
    assert response.status_code == 201, response.text
    return email, code


def test_w9_a1_reset_flow_and_session_revoke(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    email, _ = _register_user(client, postgres_url)

    # forgot → local dev mode returns the link inline (no SMTP configured).
    response = _forgot(client, email)
    assert response.status_code == 200, response.text
    reset_url = str(response.json().get("reset_url") or "")
    assert reset_url.startswith(f"{'https://w9.example'}/reset?token=")
    token = _token_from_url(reset_url)

    # The just-issued session is still valid until the token is redeemed.
    assert client.get("/api/v1/me").status_code == 200

    response = _reset(client, token, "new-password-2")
    assert response.status_code == 200, response.text

    # Sessions revoked on reset — the old cookie no longer authorizes.
    assert client.get("/api/v1/me").status_code == 401

    # Old password rejected, new password accepted.
    assert _login(client, email, "old-password-1").status_code == 401
    assert _login(client, email, "new-password-2").status_code == 200


def test_w9_a1_token_single_use(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    email, _ = _register_user(client, postgres_url)

    token = _token_from_url(_forgot(client, email).json()["reset_url"])
    assert _reset(client, token, "new-password-2").status_code == 200
    second = _reset(client, token, "new-password-3")
    assert second.status_code == 400
    assert second.json()["code"] == "RESET_INVALID"
    # And the first reset's password is the live one.
    assert _login(client, email, "new-password-2").status_code == 200


def test_w9_a1_only_newest_link_works(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    email, _ = _register_user(client, postgres_url)

    first = _token_from_url(_forgot(client, email).json()["reset_url"])
    second = _token_from_url(_forgot(client, email).json()["reset_url"])
    assert first != second

    stale = _reset(client, first, "new-password-2")
    assert stale.status_code == 400
    assert stale.json()["code"] == "RESET_INVALID"
    assert _reset(client, second, "new-password-2").status_code == 200


def test_w9_a1_unknown_email_same_shape(postgres_url: str):
    """No user enumeration: unknown email returns the same 200 body."""
    app = _app(postgres_url)
    client = TestClient(app)
    response = _forgot(client, f"ghost-{uuid.uuid4().hex[:8]}@w9.example")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    # Nothing was persisted.
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        assert db.scalars(select(PasswordReset)).all() == []
    engine.dispose()


def test_w9_a1_expired_token_rejected(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    email, _ = _register_user(client, postgres_url)

    token = _token_from_url(_forgot(client, email).json()["reset_url"])
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PasswordReset).values(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        db.commit()
    engine.dispose()
    response = _reset(client, token, "new-password-2")
    assert response.status_code == 400
    assert response.json()["code"] == "RESET_INVALID"
    # Password unchanged.
    assert _login(client, email, "old-password-1").status_code == 200


def test_w9_a1_capabilities_and_cloud_shape(postgres_url: str):
    """local advertises the flow; cloud without SMTP cannot deliver a link."""
    local = TestClient(_app(postgres_url))
    caps = local.get("/api/v1/auth/capabilities").json()
    assert caps["password_reset"] is True

    # https base_url so secure cookies round-trip like they do behind Caddy.
    cloud = TestClient(
        _app(postgres_url, mode="cloud"), base_url="https://testserver"
    )
    caps = cloud.get("/api/v1/auth/capabilities").json()
    assert caps["password_reset"] is False

    email, _ = _register_user(local, postgres_url)
    # Cloud forgot is still 200 with the same shape — nothing leaks.
    response = _forgot(cloud, email)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_w9_a1_reset_needs_valid_token_and_password(postgres_url: str):
    app = _app(postgres_url)
    client = TestClient(app)
    bad = _reset(client, "not-a-real-token", "new-password-2")
    assert bad.status_code == 400
    assert bad.json()["code"] == "RESET_INVALID"

    email, _ = _register_user(client, postgres_url)
    token = _token_from_url(_forgot(client, email).json()["reset_url"])
    short = _reset(client, token, "x" * 7)
    assert short.status_code == 400
    assert short.json()["code"] == "INVALID_INPUT"
    # Token survives a failed validation — still redeemable.
    assert _reset(client, token, "new-password-2").status_code == 200
