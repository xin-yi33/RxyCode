"""WEB-W2-C04. A lost Redis notify still delivers the committed seq, and disconnect does not cancel."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import redis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.events.store import append_event
from rxycode_server.main import create_app
from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import Organization, Project, SessionRow, User
from rxycode_server.runs.service import create_run

ORIGIN = "http://127.0.0.1"
SECRET = "local-web-secret-value-32bytes!!"
_REDIS = "rxy-w2c04-redis"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False)


def _redis_url() -> str:
    _docker("rm", "-f", _REDIS)
    started = _docker("run", "-d", "--name", _REDIS, "-p", "127.0.0.1:56380:6379", "redis:7")
    assert started.returncode == 0, started.stderr
    deadline = time.time() + 30
    while time.time() < deadline:
        ping = _docker("exec", _REDIS, "redis-cli", "ping")
        if ping.stdout.strip() == "PONG":
            return "redis://127.0.0.1:56380/0"
        time.sleep(0.5)
    raise RuntimeError("redis did not become ready")


def test_w2_c04_integration(postgres_url: str):
    """The open SSE stream delivers seq 43 from PostgreSQL when Redis never publishes it."""
    upgrade_head(postgres_url)
    redis_url = _redis_url()
    engine = create_engine(postgres_url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c04m", github_id="gh-c04m", kind="github"))
        db.add(Organization(id="org-c04m", tenant_id="tenant-c04m"))
        db.add(Project(id="project-c04m", tenant_id="tenant-c04m", name="app", repo_config={}))
        db.add(SessionRow(id=session_id, tenant_id="tenant-c04m", project_id="project-c04m", title="m"))
        db.commit()
    engine.dispose()
    app = create_app(postgres_url, mode="local", secret=SECRET, allowed_origins=[ORIGIN])
    app.state.redis = redis.Redis.from_url(redis_url, decode_responses=True)
    client = TestClient(app)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    assert client.post(
        "/api/v1/auth/local/login",
        headers={"X-CSRF-Token": csrf, "Origin": ORIGIN, "X-Local-Secret": SECRET},
    ).status_code == 200
    me = client.get("/api/v1/me").json()
    tenant_id = me["organization"]["tenant_id"]
    # The pre-seeded session is a different tenant. Open one for this login.
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": ORIGIN, "X-Local-Secret": SECRET}
    project = client.post("/api/v1/projects", json={"name": "sse", "repo_config": {}}, headers=headers)
    opened = client.post(
        f"/api/v1/projects/{project.json()['id']}/sessions",
        json={"title": "sse"},
        headers=headers,
    )
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=opened.json()["id"],
        message="follow",
        target_id="local:1",
        permission_profile="workspace-write",
        request_id="req-follow",
    )
    for seq in range(2, 43):
        append_event(
            postgres_url,
            tenant_id=tenant_id,
            run_id=created.run_id,
            event_type="assistant.delta",
            payload={"n": seq},
        )
    body: list[str] = []
    errors: list[BaseException] = []

    def read_stream() -> None:
        try:
            with client.stream(
                "GET",
                f"/api/v1/runs/{created.run_id}/events",
                params={"after_seq": 42, "follow": 1},
            ) as response:
                body.append(f"{response.status_code}\n" + "".join(response.iter_text()))
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=read_stream)
    reader.start()
    time.sleep(0.15)
    append_event(
        postgres_url,
        tenant_id=tenant_id,
        run_id=created.run_id,
        event_type="assistant.delta",
        payload={"n": 43, "gap": True},
    )
    reader.join(timeout=5)
    assert reader.is_alive() is False
    assert errors == []
    assert "id: 43" in body[0]
    assert body[0].count("id: 43") == 1
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM runs WHERE id = :id"), {"id": created.run_id}).scalar()
    engine.dispose()
    assert status == "pending"
    del session_id
