"""WEB-W9-A1. Password reset: token lifecycle, delivery modes, session revoke."""

from __future__ import annotations

import logging
import re
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
    assert caps["reset_delivery"] == "none"
    assert caps["password_reset"] is False


def test_w9_a1_operator_log_delivery(postgres_url: str, caplog):
    """Self-hosted cloud + operator-log flag: the link lands in the api log,
    the response names the channel only — deploys without SMTP stay usable."""
    app = _app(postgres_url, mode="cloud")
    app.state.reset_operator_log = True
    cloud = TestClient(app, base_url="https://testserver")

    caps = cloud.get("/api/v1/auth/capabilities").json()
    assert caps["password_reset"] is True
    assert caps["reset_delivery"] == "operator-log"

    email, _ = _register_user(cloud, postgres_url)
    with caplog.at_level(logging.WARNING, logger="rxycode_server.api.auth"):
        response = _forgot(cloud, email)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body.get("delivery") == "operator-log"
    assert "reset_url" not in body  # the URL never leaves the host

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "password reset link" in logged and email in logged
    match = re.search(r"/reset\?token=(\S+)", logged)
    assert match, caplog.records
    token = match.group(1)
    assert _reset(cloud, token, "new-password-2").status_code == 200
    assert _login(cloud, email, "new-password-2").status_code == 200


def _smtp_app(postgres_url: str, monkeypatch) -> tuple[object, list[str]]:
    """Cloud app with SMTP configured; send_mail is stubbed to capture bodies."""
    app = _app(postgres_url, mode="cloud")
    app.state.smtp_url = "smtps://u:p@smtp.example:465"
    outbox: list[str] = []

    def _fake_send(*_args, **kwargs):
        outbox.append(str(kwargs.get("body") or ""))
        return True

    import rxycode_server.mailer as mailer

    monkeypatch.setattr(mailer, "send_mail", _fake_send)
    return app, outbox


def _code_from(outbox: list[str]) -> str:
    match = re.search(r"验证码：(\d{6})", outbox[-1])
    assert match, outbox
    return match.group(1)


def _reset_code(client: TestClient, email: str, code: str, password: str):
    return client.post(
        "/api/v1/auth/reset",
        json={"email": email, "code": code, "password": password},
        headers=_headers(_csrf(client)),
    )


def test_w9_a1_smtp_code_flow(postgres_url: str, monkeypatch):
    """SMTP delivery issues a 6-digit code; email+code redeems it."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    email, _ = _register_user(client, postgres_url)

    response = _forgot(client, email)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "delivery": "smtp"}
    assert outbox and "/reset?token=" not in outbox[-1]
    code = _code_from(outbox)

    # Wrong code does not reveal anything and does not burn early.
    bad = _reset_code(client, email, "000000" if code != "000000" else "111111", "new-password-2")
    assert bad.status_code == 400
    assert bad.json()["code"] == "RESET_INVALID"

    assert _reset_code(client, email, code, "new-password-2").status_code == 200
    assert _login(client, email, "new-password-2").status_code == 200
    # Code is single-use.
    again = _reset_code(client, email, code, "new-password-3")
    assert again.status_code == 400


def test_w9_a1_smtp_code_attempts_burn(postgres_url: str, monkeypatch):
    """Five wrong codes burn the outstanding one."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    app.state.auth_rate = None  # isolate the cumulative-attempts counter
    client = TestClient(app, base_url="https://testserver")
    email, _ = _register_user(client, postgres_url)

    _forgot(client, email)
    code = _code_from(outbox)
    wrong = "999999" if code != "999999" else "888888"
    for i in range(5):
        r = _reset_code(client, email, wrong, "new-password-2")
        assert r.status_code == 400
    # Even the real code is dead now.
    assert _reset_code(client, email, code, "new-password-2").status_code == 400
    assert _login(client, email, "old-password-1").status_code == 200


def test_w9_a1_smtp_code_expiry_and_validation(postgres_url: str, monkeypatch):
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    email, _ = _register_user(client, postgres_url)

    _forgot(client, email)
    code = _code_from(outbox)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PasswordReset).values(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        db.commit()
    engine.dispose()
    assert _reset_code(client, email, code, "new-password-2").status_code == 400

    # Shape validation: non-6-digit codes and short passwords are INVALID_INPUT.
    _forgot(client, email)
    code = _code_from(outbox)
    bad_shape = _reset_code(client, email, "abc", "new-password-2")
    assert bad_shape.status_code == 400
    assert bad_shape.json()["code"] == "INVALID_INPUT"
    bad_pw = _reset_code(client, email, code, "x" * 7)
    assert bad_pw.json()["code"] == "INVALID_INPUT"
    # Code survives bad-password attempts.
    assert _reset_code(client, email, code, "new-password-2").status_code == 200


def test_w9_a1_smtp_send_failure_falls_back(postgres_url: str, monkeypatch, caplog):
    """SMTP down + operator-log enabled → a redeemable link goes to the log
    and the minted code is burned (the operator-log UI only handles links)."""
    app = _app(postgres_url, mode="cloud")
    app.state.smtp_url = "smtps://u:p@smtp.example:465"
    app.state.reset_operator_log = True

    import rxycode_server.mailer as mailer

    monkeypatch.setattr(mailer, "send_mail", lambda *a, **k: False)
    client = TestClient(app, base_url="https://testserver")
    email, _ = _register_user(client, postgres_url)

    with caplog.at_level(logging.WARNING, logger="rxycode_server.api.auth"):
        response = _forgot(client, email)
    assert response.json().get("delivery") == "operator-log"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    match = re.search(r"operator outbox\): (\S+)", logged)
    assert match, logged
    token = _token_from_url(match.group(1))
    assert _reset(client, token, "new-password-2").status_code == 200
    assert _login(client, email, "new-password-2").status_code == 200


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
