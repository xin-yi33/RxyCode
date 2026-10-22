"""W10 / UI-2026-10-22 contract tests: sessions lifecycle, projects, search,
preferences, schedules, security extension endpoints.

Covers the acceptance cards in docs/.../requirements/UI-2026-10-22 —
API-level contracts only (UI behavior is covered by Playwright separately).
"""

from __future__ import annotations

import sys
import uuid
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

from rxycode_server.api.auth import invite_digest  # noqa: E402
from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.models import Invite, Run  # noqa: E402

ORIGIN = "https://w10.example"
SECRET = "w10-web-secret-value-32bytes-long!!"


def _app(postgres_url: str, **kwargs):
    return create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        **kwargs,
    )


def _csrf(client: TestClient) -> str:
    return client.get("/api/v1/auth/csrf").json()["csrf_token"]


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": ORIGIN}


def _client(postgres_url: str, email: str, *, app=None) -> tuple[TestClient, dict]:
    code = "w10-" + uuid.uuid4().hex[:12]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(
            Invite(code_hash=invite_digest(code), max_uses=1, used=0, note="w10")
        )
        db.commit()
    engine.dispose()
    if app is None:
        app = _app(postgres_url)
    client = TestClient(app)
    from tests.web.w9.test_auth import _solve_captcha

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": code,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert response.status_code == 201, response.text
    return client, response.json()


def _post_task(client: TestClient, message: str, **extra):
    return client.post(
        "/api/v1/tasks",
        json={
            "message": message,
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
            **extra,
        },
        headers=_headers(_csrf(client)),
    )


def _post_run(client: TestClient, session_id: str, message: str):
    return client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "message": message,
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
        },
        headers=_headers(_csrf(client)),
    )


def _finish_run(postgres_url: str, run_id: str, status: str = "succeeded") -> None:
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(update(Run).where(Run.id == run_id).values(status=status))
        db.commit()
    engine.dispose()


# ---- sessions lifecycle -----------------------------------------------------


def test_w10_session_patch_archive_unarchive(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "lifecycle@example.com")
    made = _post_task(client, "archive me please")
    assert made.status_code == 202
    session_id = made.json()["session_id"]
    _finish_run(postgres_url, made.json()["run_id"])

    # rename + pin via PATCH
    patched = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "renamed chat", "pinned": True},
        headers=_headers(_csrf(client)),
    )
    assert patched.status_code == 200, patched.text
    item = patched.json()["session"]
    assert item["title"] == "renamed chat"
    assert item["pinned"] is True
    revision = item["revision"]

    # stale revision rejected
    stale = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "stale", "expected_revision": 0},
        headers=_headers(_csrf(client)),
    )
    assert stale.status_code == 409

    # archive → submit refused 409 SESSION_ARCHIVED
    archived = client.post(
        f"/api/v1/sessions/{session_id}/archive",
        json={"expected_revision": revision},
        headers=_headers(_csrf(client)),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["session"]["archived"] is True

    refused = _post_run(client, session_id, "blocked")
    assert refused.status_code == 409
    assert refused.json()["code"] == "SESSION_ARCHIVED"

    # archived session is hidden from the default list, visible with filter
    default_list = client.get("/api/v1/sessions").json()["sessions"]
    assert all(s["id"] != session_id for s in default_list)
    archived_list = client.get(
        "/api/v1/sessions", params={"archived": "true"}
    ).json()["sessions"]
    assert any(s["id"] == session_id for s in archived_list)

    # unarchive → submit works again
    revived = client.post(
        f"/api/v1/sessions/{session_id}/unarchive",
        json={},
        headers=_headers(_csrf(client)),
    )
    assert revived.status_code == 200
    allowed = _post_run(client, session_id, "back alive")
    assert allowed.status_code == 202


def test_w10_session_delete_tombstone(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "deleter@example.com")
    made = _post_task(client, "delete me")
    session_id = made.json()["session_id"]
    _finish_run(postgres_url, made.json()["run_id"])

    # delete requires confirm
    refused = client.request("DELETE", 
        f"/api/v1/sessions/{session_id}",
        json={"confirm": False},
        headers=_headers(_csrf(client)),
    )
    assert refused.status_code in (400, 422)

    gone = client.request("DELETE", 
        f"/api/v1/sessions/{session_id}",
        json={"confirm": True},
        headers=_headers(_csrf(client)),
    )
    assert gone.status_code == 204

    # deleted session is 404 on read paths and submit
    detail = client.get(f"/api/v1/sessions/{session_id}")
    assert detail.status_code == 404
    assert client.get("/api/v1/sessions").json()["sessions"] == []
    submit = _post_run(client, session_id, "ghost")
    assert submit.status_code == 404
    # search must not surface it either
    hits = client.get("/api/v1/search", params={"q": "delete"}).json()["hits"]
    assert all(h["session_id"] != session_id for h in hits)


# ---- projects ---------------------------------------------------------------


def test_w10_projects_crud_and_conflicts(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, me = _client(postgres_url, "projects@example.com")
    default_id = me["default_project_id"]

    created = client.post(
        "/api/v1/projects",
        json={"name": "Alpha", "memory_mode": "project_only"},
        headers=_headers(_csrf(client)),
    )
    assert created.status_code in (200, 201), created.text
    project = created.json()["project"]
    assert project["memory_mode"] == "project_only"

    # duplicate name conflicts
    dup = client.post(
        "/api/v1/projects",
        json={"name": "Alpha"},
        headers=_headers(_csrf(client)),
    )
    assert dup.status_code == 409

    # patch rename
    patched = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Beta"},
        headers=_headers(_csrf(client)),
    )
    assert patched.status_code == 200
    assert patched.json()["project"]["name"] == "Beta"

    # default project cannot be deleted
    denied = client.request("DELETE", 
        f"/api/v1/projects/{default_id}",
        json={},
        headers=_headers(_csrf(client)),
    )
    assert denied.status_code == 403

    # delete keeps sessions in default project
    made = _post_task(client, "project task", project_id=project["id"])
    assert made.status_code == 202, made.text
    _finish_run(postgres_url, made.json()["run_id"])
    deleted = client.request("DELETE", 
        f"/api/v1/projects/{project['id']}",
        json={"keep_sessions": True},
        headers=_headers(_csrf(client)),
    )
    assert deleted.status_code == 204
    session = client.get(f"/api/v1/sessions/{made.json()['session_id']}")
    assert session.status_code == 200
    assert session.json()["project_id"] == default_id


# ---- search ------------------------------------------------------------------


def test_w10_search_chinese_substring(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "searcher@example.com")
    other, _me2 = _client(postgres_url, "stranger@example.com")
    made = _post_task(client, "帮我修复登录页面的样式问题")
    assert made.status_code == 202
    session_id = made.json()["session_id"]

    hits = client.get("/api/v1/search", params={"q": "登录页面"}).json()["hits"]
    assert any(h["session_id"] == session_id for h in hits)
    chat_hit = next(h for h in hits if h["session_id"] == session_id)
    assert chat_hit["type"] == "chat"
    assert chat_hit["href"].startswith("/app/")

    # cross-tenant invisible
    foreign = other.get("/api/v1/search", params={"q": "登录页面"}).json()["hits"]
    assert all(h["session_id"] != session_id for h in foreign)

    # empty query returns recent authorized chats, never strangers'
    recent = client.get("/api/v1/search").json()["hits"]
    assert any(h["session_id"] == session_id for h in recent)


# ---- preferences --------------------------------------------------------------


def test_w10_preferences_get_patch(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "prefs@example.com")
    got = client.get("/api/v1/me/preferences")
    assert got.status_code == 200
    body = got.json()
    assert body["locale"] == "auto"
    revision = body["revision"]

    patched = client.patch(
        "/api/v1/me/preferences",
        json={"locale": "en", "expected_revision": revision},
        headers=_headers(_csrf(client)),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["locale"] == "en"

    # stale revision rejected
    stale = client.patch(
        "/api/v1/me/preferences",
        json={"locale": "zh-CN", "expected_revision": revision},
        headers=_headers(_csrf(client)),
    )
    assert stale.status_code == 409

    # junk values rejected
    bad = client.patch(
        "/api/v1/me/preferences",
        json={"appearance": {"mode": "neon"}},
        headers=_headers(_csrf(client)),
    )
    assert bad.status_code in (400, 422)


# ---- schedules -----------------------------------------------------------------


def test_w10_schedules_crud_and_run_now(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, me = _client(postgres_url, "scheduler@example.com")
    made = _post_task(client, "schedule host")
    session_id = made.json()["session_id"]
    _finish_run(postgres_url, made.json()["run_id"])

    created = client.post(
        "/api/v1/schedules",
        json={
            "project_id": me["default_project_id"],
            "session_id": session_id,
            "name": "hourly check",
            "message": "run the checks",
            "rule": {"kind": "interval", "every": 1, "unit": "hours"},
            "timezone": "Asia/Shanghai",
            "request_id": "sched-" + uuid.uuid4().hex[:16],
        },
        headers=_headers(_csrf(client)),
    )
    assert created.status_code == 201, created.text
    schedule = created.json()["schedule"]
    assert schedule["next_fire"]

    listing = client.get("/api/v1/schedules").json()["schedules"]
    assert any(s["id"] == schedule["id"] for s in listing)

    detail = client.get(f"/api/v1/schedules/{schedule['id']}")
    assert detail.status_code == 200
    assert detail.json()["schedule"]["timezone"] == "Asia/Shanghai"

    # bad timezone refused
    bad_tz = client.post(
        "/api/v1/schedules",
        json={
            "project_id": me["default_project_id"],
            "session_id": session_id,
            "message": "x",
            "rule": {"kind": "interval", "every": 1, "unit": "hours"},
            "timezone": "Not/AZone",
        },
        headers=_headers(_csrf(client)),
    )
    assert bad_tz.status_code in (400, 422)

    # run-now creates a real run, idempotent on request_id
    request_id = "now-" + uuid.uuid4().hex[:16]
    fired = client.post(
        f"/api/v1/schedules/{schedule['id']}/run-now",
        json={"request_id": request_id, "allow_billable": True},
        headers=_headers(_csrf(client)),
    )
    assert fired.status_code == 202, fired.text
    replay = client.post(
        f"/api/v1/schedules/{schedule['id']}/run-now",
        json={"request_id": request_id, "allow_billable": True},
        headers=_headers(_csrf(client)),
    )
    assert replay.status_code == 202
    assert replay.json()["run_id"] == fired.json()["run_id"]

    # pause + delete
    paused = client.patch(
        f"/api/v1/schedules/{schedule['id']}",
        json={"enabled": False},
        headers=_headers(_csrf(client)),
    )
    assert paused.status_code == 200
    assert paused.json()["schedule"]["enabled"] is False
    deleted = client.request("DELETE", 
        f"/api/v1/schedules/{schedule['id']}",
        headers=_headers(_csrf(client)),
    )
    assert deleted.status_code == 204


# ---- security -------------------------------------------------------------------


def test_w10_security_overview_reauth_sessions(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "secure@example.com")

    overview = client.get("/api/v1/auth/security")
    assert overview.status_code == 200
    body = overview.json()
    assert body["password_present"] is True
    assert body["totp_enabled"] is False

    # wrong password → 401, no ticket
    denied = client.post(
        "/api/v1/auth/reauthenticate",
        json={"method": "password", "purpose": "session_revoke", "password": "wrong"},
        headers=_headers(_csrf(client)),
    )
    assert denied.status_code == 401

    ticket = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "method": "password",
            "purpose": "session_revoke",
            "password": "password-123",
        },
        headers=_headers(_csrf(client)),
    )
    assert ticket.status_code == 200
    token = ticket.json()["reauth_token"]

    sessions = client.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(sessions) >= 1
    current = next(s for s in sessions if s["current"])
    assert current["revoked"] is False

    # bad purpose is rejected at reauthenticate
    bad_purpose = client.post(
        "/api/v1/auth/reauthenticate",
        json={"method": "password", "purpose": "admin_panel", "password": "password-123"},
        headers=_headers(_csrf(client)),
    )
    assert bad_purpose.status_code == 422
    assert token  # silence unused warning


def test_w10_totp_enroll_confirm_disable(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "totp@example.com")
    pyotp = pytest.importorskip("pyotp")

    ticket = client.post(
        "/api/v1/auth/reauthenticate",
        json={"method": "password", "purpose": "totp_setup", "password": "password-123"},
        headers=_headers(_csrf(client)),
    ).json()["reauth_token"]

    setup = client.post(
        "/api/v1/auth/mfa/totp/setup",
        json={"reauth_token": ticket},
        headers=_headers(_csrf(client)),
    )
    assert setup.status_code == 200, setup.text
    body = setup.json()
    assert body["secret"]
    code = pyotp.TOTP(body["secret"]).now()

    confirm = client.post(
        "/api/v1/auth/mfa/totp/confirm",
        json={"setup_id": body["setup_id"], "code": code},
        headers=_headers(_csrf(client)),
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["enabled"] is True
    assert len(confirm.json()["backup_codes"]) > 0

    overview = client.get("/api/v1/auth/security").json()
    assert overview["totp_enabled"] is True

    # disable with reauth + fresh code
    ticket2 = client.post(
        "/api/v1/auth/reauthenticate",
        json={"method": "password", "purpose": "totp_remove", "password": "password-123"},
        headers=_headers(_csrf(client)),
    ).json()["reauth_token"]
    code2 = pyotp.TOTP(body["secret"]).now()
    removed = client.request("DELETE", 
        "/api/v1/auth/mfa/totp",
        json={"reauth_token": ticket2, "code": code2},
        headers=_headers(_csrf(client)),
    )
    assert removed.status_code == 204
    assert client.get("/api/v1/auth/security").json()["totp_enabled"] is False


# ---- notifications ---------------------------------------------------------------


def test_w10_notification_preferences(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "notify@example.com")
    prefs = client.get("/api/v1/me/notification-preferences")
    assert prefs.status_code == 200, prefs.text
    body = prefs.json()
    assert body["categories"]
    cat = body["categories"][0]

    toggled = client.patch(
        "/api/v1/me/notification-preferences",
        json={
            "category_id": cat["id"],
            "selected_channels": ["in_app"],
            "expected_revision": body["revision"],
        },
        headers=_headers(_csrf(client)),
    )
    assert toggled.status_code == 200, toggled.text

    listing = client.get("/api/v1/notifications")
    assert listing.status_code == 200
