"""WEB-W9-A1+. Register-verify codes, code login, ALTCHA gate."""

from __future__ import annotations

import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.web.w9.test_auth import (
    _app,
    _csrf,
    _headers,
    _invite,
    _login,
    _solve_captcha,
)
from tests.web.w9.test_password_reset import (
    _code_from,
    _new_email,
    _register_user,
    _send_register_code,
    _smtp_app,
)


def _login_code_send(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/login/code",
        json={"email": email, "captcha": _solve_captcha(client)},
        headers=_headers(_csrf(client)),
    )


def _login_with_code(client: TestClient, email: str, code: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "code": code, "captcha": _solve_captcha(client)},
        headers=_headers(_csrf(client)),
    )


def test_w9_a1_register_requires_email_code(postgres_url: str, monkeypatch):
    """SMTP deploys: register without / with a wrong / with the right code."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    caps = client.get("/api/v1/auth/capabilities").json()
    assert caps["code_delivery"] == "smtp"
    assert caps["captcha"] == "altcha"

    email = _new_email()
    invite = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, invite)

    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": invite,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert r.status_code == 400
    assert r.json()["code"] == "CODE_REQUIRED"

    _send_register_code(client, email)
    code = _code_from(outbox)
    wrong = "000000" if code != "000000" else "111111"
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": invite,
            "code": wrong,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert r.status_code == 400
    assert r.json()["code"] == "CODE_INVALID"

    # invite is single-use — issue a second seat for the real register.
    _invite(postgres_url, invite + "b")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": invite + "b",
            "code": code,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert response.status_code == 201, response.text
    assert _login(client, email, "password-123").status_code == 200


def test_w9_a1_login_via_email_code(postgres_url: str, monkeypatch):
    """Code login: request code → redeem → session; wrong code → 401."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    email = _new_email()
    _send_register_code(client, email)
    _register_user(client, postgres_url, _code_from(outbox), email)

    outbox.clear()
    sent = _login_code_send(client, email)
    assert sent.status_code == 200
    assert sent.json()["delivery"] == "smtp"
    code = _code_from(outbox)

    wrong = _login_with_code(client, email, "000000" if code != "000000" else "111111")
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "INVALID_CREDENTIALS"

    ok = _login_with_code(client, email, code)
    assert ok.status_code == 200, ok.text
    assert client.get("/api/v1/me").status_code == 200
    # single-use
    assert _login_with_code(client, email, code).status_code == 401

    # non-enumerating: unknown email still 200 + delivery shape
    ghost = _login_code_send(client, "ghost-" + uuid.uuid4().hex[:8] + "@w9.example")
    assert ghost.status_code == 200
    assert ghost.json()["delivery"] == "smtp"


def test_w9_a1_captcha_gates(postgres_url: str, monkeypatch):
    """No captcha / forged payload / replayed payload all die at the gate."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    client = TestClient(app, base_url="https://testserver")
    email = _new_email()

    no = client.post(
        "/api/v1/auth/register/code",
        json={"email": email},
        headers=_headers(_csrf(client)),
    )
    assert no.status_code == 400 and no.json()["code"] == "CAPTCHA_INVALID"

    forged = client.post(
        "/api/v1/auth/register/code",
        json={"email": email, "captcha": "Zm9v"},  # base64 "foo"
        headers=_headers(_csrf(client)),
    )
    assert forged.status_code == 400 and forged.json()["code"] == "CAPTCHA_INVALID"

    payload = _solve_captcha(client)
    ok = client.post(
        "/api/v1/auth/register/code",
        json={"email": email, "captcha": payload},
        headers=_headers(_csrf(client)),
    )
    assert ok.status_code == 200
    # replay: the same solved challenge is single-use
    again = client.post(
        "/api/v1/auth/register/code",
        json={"email": email, "captcha": payload},
        headers=_headers(_csrf(client)),
    )
    assert again.status_code == 400 and again.json()["code"] == "CAPTCHA_INVALID"


def test_w9_a1_register_code_five_strikes(postgres_url: str, monkeypatch):
    """Five wrong register codes burn the minted one."""
    app, outbox = _smtp_app(postgres_url, monkeypatch)
    app.state.auth_rate = None
    client = TestClient(app, base_url="https://testserver")
    email = _new_email()
    invite = "w9-invite-" + uuid.uuid4().hex[:12]
    _invite(postgres_url, invite, uses=10)

    _send_register_code(client, email)
    code = _code_from(outbox)
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "password-123",
                "invite_code": invite,
                "code": wrong,
                "captcha": _solve_captcha(client),
            },
            headers=_headers(_csrf(client)),
        )
        assert r.status_code == 400
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": invite,
            "code": code,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert r.status_code == 400  # burned — the real code no longer works
