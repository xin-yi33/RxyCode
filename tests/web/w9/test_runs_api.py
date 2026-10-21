"""WEB-W9-B2/B4. Task submission, session history, FIFO claim order, quotas."""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.api.auth import invite_digest  # noqa: E402
from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Invite,
    Run,
    RunEvent,
    SessionRow,
)

ORIGIN = "https://w9.example"
SECRET = "w9-web-secret-value-32bytes-long!!"


def _app(postgres_url: str, **kwargs):
    # local mode: non-secure cookies flow through TestClient's http transport.
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
    """Register through the default invite mode and return an authed client."""
    code = "w9-run-" + uuid.uuid4().hex[:12]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(
            Invite(code_hash=invite_digest(code), max_uses=1, used=0, note="w9-runs")
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


def _post_task(client: TestClient, message: str, request_id: str | None = None, **extra):
    body = {
        "message": message,
        "request_id": request_id or ("req-" + uuid.uuid4().hex[:16]),
        "permission_profile": "confirm",
        **extra,
    }
    return client.post("/api/v1/tasks", json=body, headers=_headers(_csrf(client)))


def _post_run(client: TestClient, session_id: str, message: str, request_id: str | None = None):
    return client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "message": message,
            "request_id": request_id or ("req-" + uuid.uuid4().hex[:16]),
            "permission_profile": "confirm",
        },
        headers=_headers(_csrf(client)),
    )


def test_w9_b2_task_creates_session_and_run(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, me = _client(postgres_url, "tasker@example.com")
    response = _post_task(client, "first line\nsecond line of the task")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["events_url"] == f"/api/v1/runs/{body['run_id']}/events"
    with Session(create_engine(postgres_url)) as db:
        run = db.get(Run, body["run_id"])
        assert run is not None
        assert run.tenant_id == me["organization"]["tenant_id"]
        assert run.session_id == body["session_id"]
        assert (
            run.target_id
            == f"cloud:{me['organization']['tenant_id']}:{me['default_project_id']}"
        )
        assert run.created_at is not None
        created = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run.id, RunEvent.seq == 1, RunEvent.type == "run.created"
            )
        ).one()
        assert created.payload["message"].startswith("first line")
        assert created.payload["permission_profile"] == "confirm"
        session = db.get(SessionRow, run.session_id)
        assert session is not None
        assert session.title == "first line second line of the task"[:40]
        assert "\n" not in session.title
        assert session.updated_at is not None


def test_w9_b2_request_id_idempotency(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "idem@example.com")
    request_id = "req-" + uuid.uuid4().hex[:16]
    first = _post_task(client, "do the thing", request_id)
    assert first.status_code == 202
    replay = _post_task(client, "do the thing", request_id)
    assert replay.status_code == 202
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert replay.json()["session_id"] == first.json()["session_id"]
    # no second session was created for the replay
    sessions = client.get("/api/v1/sessions").json()["sessions"]
    assert len(sessions) == 1
    conflict = _post_task(client, "different content", request_id)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REQUEST_CONFLICT"


def test_w9_b2_session_runs_and_active_cap(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "multi@example.com")
    app2 = _app(postgres_url)
    other, _me2 = _client(postgres_url, "stranger@example.com", app=app2)

    first = _post_task(client, "seed run")
    session_id = first.json()["session_id"]
    # second active run on the same session -> RUN_ACTIVE
    active = _post_run(client, session_id, "still busy")
    assert active.status_code == 409
    assert active.json()["code"] == "RUN_ACTIVE"
    # another tenant's session is invisible
    foreign = _post_run(other, session_id, "intrude")
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "SESSION_NOT_FOUND"

    # finish the first run out-of-band, then a second run may be admitted
    with Session(create_engine(postgres_url)) as db:
        db.execute(
            update(Run).where(Run.id == first.json()["run_id"]).values(status="succeeded")
        )
        db.commit()
    second = _post_run(client, session_id, "follow-up")
    assert second.status_code == 202, second.text
    listing = client.get(f"/api/v1/sessions/{session_id}/runs")
    assert listing.status_code == 200
    runs = listing.json()["runs"]
    assert [row["run_id"] for row in runs] == [
        second.json()["run_id"],
        first.json()["run_id"],
    ]
    assert runs[0]["message"] == "follow-up"


def test_w9_b2_session_list_and_cursor(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "history@example.com")
    runs = []
    sessions = []
    for index in range(3):
        made = _post_task(client, f"task number {index}")
        assert made.status_code == 202
        runs.append(made.json()["run_id"])
        sessions.append(made.json()["session_id"])
        if index < 2:
            with Session(create_engine(postgres_url)) as db:
                db.execute(update(Run).where(Run.id == runs[-1]).values(status="succeeded"))
                db.commit()
            _post_run(client, sessions[-1], f"task {index} extra")

    listing = client.get("/api/v1/sessions")
    assert listing.status_code == 200
    items = listing.json()["sessions"]
    assert len(items) == 3
    assert all(item["last_run"] is not None for item in items)
    by_id = {item["id"]: item for item in items}
    assert by_id[sessions[2]]["last_run"]["run_id"] == runs[2]
    # sessions[0]'s last run is the still-pending extra run, not the finished one
    assert by_id[sessions[0]]["last_run"]["status"] == "pending"
    assert by_id[sessions[0]]["last_run"]["run_id"] != runs[0]

    # cursor pagination over a session with 2 runs
    page1 = client.get(f"/api/v1/sessions/{sessions[0]}/runs", params={"limit": 1})
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["runs"]) == 1
    assert body1["next_cursor"]
    page2 = client.get(
        f"/api/v1/sessions/{sessions[0]}/runs",
        params={"limit": 1, "before": body1["next_cursor"]},
    )
    body2 = page2.json()
    assert len(body2["runs"]) == 1
    assert body2["runs"][0]["run_id"] != body1["runs"][0]["run_id"]
    assert {body1["runs"][0]["run_id"], body2["runs"][0]["run_id"]} == {
        row.id
        for row in Session(create_engine(postgres_url))
        .scalars(select(Run).where(Run.session_id == sessions[0]))
        .all()
    }
    bad = client.get(f"/api/v1/sessions/{sessions[0]}/runs", params={"before": "garbage"})
    assert bad.status_code == 400


def test_w9_b2_validation_and_cross_tenant(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "rules@example.com")
    other, _me2 = _client(postgres_url, "peer@example.com")
    # message/request_id/profile validation
    bad_profile = _post_task(client, "x", permission_profile="sudo")
    assert bad_profile.status_code == 400
    short_id = client.post(
        "/api/v1/tasks",
        json={"message": "x", "request_id": "tiny", "permission_profile": "confirm"},
        headers=_headers(_csrf(client)),
    )
    assert short_id.status_code == 400
    blank = client.post(
        "/api/v1/tasks",
        json={"message": "   ", "request_id": "req-" + uuid.uuid4().hex[:16],
              "permission_profile": "confirm"},
        headers=_headers(_csrf(client)),
    )
    assert blank.status_code == 400
    # foreign project refused
    mine = _post_task(client, "mine")
    foreign_project = _post_task(
        client, "intrude", project_id="project-does-not-exist"
    )
    assert foreign_project.status_code == 404
    # other tenant's run history is 404
    foreign_session = mine.json()["session_id"]
    denied = other.get(f"/api/v1/sessions/{foreign_session}/runs")
    assert denied.status_code == 404
    denied_run = other.get(f"/api/v1/runs/{mine.json()['run_id']}")
    assert denied_run.status_code == 404


def test_w9_b2_post_returns_fast_without_worker(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """Model/worker unreachable still yields a durable pending run inside 1s."""
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "quick@example.com")
    started = time.monotonic()
    response = _post_task(client, "returns before any worker exists")
    assert time.monotonic() - started < 1.0
    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_w9_b2_fifo_claim_order(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    client, _me = _client(postgres_url, "fifo@example.com")
    first = _post_task(client, "early task")
    second = _post_task(client, "late task")
    assert first.status_code == 202 and second.status_code == 202
    early, late = first.json()["run_id"], second.json()["run_id"]
    # force a visible created_at gap so the order cannot be explained by id
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(Run)
            .where(Run.id == late)
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=2))
        )
        db.commit()
    engine.dispose()
    from rxycode_worker.drain import claimable_run_ids

    ids = claimable_run_ids(postgres_url, limit=10)
    assert ids[:2] == [late, early]


def test_w9_b4_concurrency_and_queue(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.setenv("RXYCODE_QUOTA_CONCURRENCY", "1")
    monkeypatch.setenv("RXYCODE_QUEUE_MAX", "2")
    app = _app(postgres_url)
    client, _me = _client(postgres_url, "busy@example.com", app=app)
    first = _post_task(client, "run one")
    assert first.status_code == 202
    second = _post_task(client, "run two")
    assert second.status_code == 429
    assert second.json() == {"code": "QUOTA_EXCEEDED", "reason": "concurrency"}
    # the refused run never occupied a worker nor created a row
    with Session(create_engine(postgres_url)) as db:
        assert db.scalars(select(Run)).all().__len__() == 1


def test_w9_b4_queue_max_is_global(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.setenv("RXYCODE_QUEUE_MAX", "1")
    app = _app(postgres_url)
    client, _me = _client(postgres_url, "first@example.com", app=app)
    assert _post_task(client, "occupies the single queue slot").status_code == 202
    other, _me2 = _client(postgres_url, "second@example.com", app=app)
    refused = _post_task(other, "queue is full")
    assert refused.status_code == 429
    assert refused.json() == {"code": "QUOTA_EXCEEDED", "reason": "queue"}


def test_w9_b4_windowed_daily_tasks(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.setenv("RXYCODE_QUOTA_TASKS_PER_DAY", "1")
    monkeypatch.setenv("RXYCODE_QUOTA_CONCURRENCY", "10")
    app = _app(postgres_url)
    client, _me = _client(postgres_url, "daily@example.com", app=app)
    first = _post_task(client, "today's task")
    assert first.status_code == 202
    refused = _post_task(client, "over the daily task ceiling")
    assert refused.status_code == 429
    assert refused.json() == {"code": "QUOTA_EXCEEDED", "reason": "task"}
    # a run older than the window no longer counts
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(Run)
            .where(Run.id == first.json()["run_id"])
            .values(
                created_at=datetime.now(timezone.utc) - timedelta(days=2),
                status="succeeded",
            )
        )
        db.commit()
    engine.dispose()
    again = _post_task(client, "next day task")
    assert again.status_code == 202, again.text


def test_w9_b4_defaults_without_env(postgres_url: str):
    from rxycode_server.quotas.service import DEFAULT_LIMITS, active_gate

    app = _app(postgres_url)  # no quota env: nothing installed
    assert active_gate()._limits == DEFAULT_LIMITS
    client, _me = _client(postgres_url, "free@example.com", app=app)
    assert _post_task(client, "one").status_code == 202
