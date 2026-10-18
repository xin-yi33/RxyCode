"""WEB-W7-C02. Reconnect after a network drop replays every seq exactly once."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import redis
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _path in (REPO, _SERVER, _WORKER, _RUNNER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.api.auth import AuthRecord, _hash_token  # noqa: E402
from rxycode_server.events.store import append_event  # noqa: E402
from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Outbox,
    Project,
    Run,
    RunEvent,
    SessionRow,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.queue import dispatch_pending  # noqa: E402

ORIGIN = "http://127.0.0.1"
SECRET = "local-web-secret-value-32bytes!!"
_REDIS = "rxy-w7c02-redis"
_STREAM = "rxycode:w7c02"
REDIS_URL = "redis://127.0.0.1:56390/0"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False)


def _redis_start() -> None:
    _docker("rm", "-f", _REDIS)
    started = _docker(
        "run", "-d", "--name", _REDIS, "-p", "127.0.0.1:56390:6379", "redis:7"
    )
    assert started.returncode == 0, started.stderr
    deadline = time.time() + 30
    while time.time() < deadline:
        if _docker("exec", _REDIS, "redis-cli", "ping").stdout.strip() == "PONG":
            return
        time.sleep(0.5)
    raise RuntimeError("redis did not become ready")


_PRODUCER = """\
import os, sys, time
import redis
from rxycode_worker.supervisor import claim, renew_lease, commit_terminal
from rxycode_server.events.store import append_event
from rxycode_worker.queue import dispatch_pending

url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
tenant = os.environ["C02_TENANT"]
worker = "worker-c02m"
client = redis.Redis.from_url(
    os.environ["C02_REDIS"], decode_responses=True,
    socket_timeout=0.3, socket_connect_timeout=0.3,
)
epoch = claim(url, run_id, worker, ttl_seconds=30)
print("PID " + str(os.getpid()), flush=True)
for i in range(40):
    if i and i % 5 == 0:
        renew_lease(url, run_id, worker, epoch, ttl_seconds=30)
    append_event(
        url, tenant_id=tenant, run_id=run_id,
        event_type="assistant.delta", payload={"n": i, "tenant": "A"},
    )
    dispatch_pending(url, client, stream=os.environ["C02_STREAM"])
    time.sleep(0.25)
commit_terminal(url, run_id, worker, epoch, "succeeded")
print("DONE", flush=True)
"""


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env.update(extra)
    parts = [str(REPO), str(_SERVER), str(_WORKER), str(_RUNNER)]
    previous = env.get("PYTHONPATH", "")
    if previous:
        parts.append(previous)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _frame_seqs(text: str) -> list[int]:
    seqs: list[int] = []
    for line in text.splitlines():
        if line.startswith("id: "):
            seqs.append(int(line[4:]))
    return seqs


def test_w7_c02_integration(postgres_url: str):
    """Disconnect mid-stream, Redis paused, reconnect: all seqs once, terminal ok."""
    upgrade_head(postgres_url)
    _redis_start()
    producer = None
    tenant_b_thread = None
    try:
        app = create_app(postgres_url, mode="local", secret=SECRET, allowed_origins=[ORIGIN])
        app.state.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        from fastapi.testclient import TestClient
        from rxycode_server.api.sse import iter_frames

        client = TestClient(app)
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf, "Origin": ORIGIN, "X-Local-Secret": SECRET}
        assert client.post("/api/v1/auth/local/login", headers=headers).status_code == 200
        tenant_a = client.get("/api/v1/me").json()["organization"]["tenant_id"]
        project = client.post(
            "/api/v1/projects", json={"name": "chaos", "repo_config": {}}, headers=headers
        )
        opened = client.post(
            f"/api/v1/projects/{project.json()['id']}/sessions",
            json={"title": "chaos"},
            headers=headers,
        )
        session_a = opened.json()["id"]
        run_a = create_run(
            postgres_url,
            tenant_id=tenant_a,
            session_id=session_a,
            message="long run",
            target_id="local:c02",
            permission_profile="workspace-write",
            request_id="req-c02-module-a",
        )

        # Tenant B: separate org/session producing cross-tenant noise.
        tenant_b = "tenant-c02-b"
        engine = create_engine(postgres_url)
        session_b = uuid.uuid4().hex
        with Session(engine) as db:
            db.add(User(id="user-c02b", github_id="gh-c02b", kind="github"))
            db.add(Organization(id="org-c02b", tenant_id=tenant_b))
            db.add(
                Project(
                    id="project-c02b", tenant_id=tenant_b, name="b", repo_config={}
                )
            )
            db.add(
                SessionRow(
                    id=session_b,
                    tenant_id=tenant_b,
                    project_id="project-c02b",
                    title="b",
                )
            )
            db.commit()
        engine.dispose()
        run_b = create_run(
            postgres_url,
            tenant_id=tenant_b,
            session_id=session_b,
            message="other tenant",
            target_id="local:c02b",
            permission_profile="workspace-write",
            request_id="req-c02-module-b",
        )

        def produce_b() -> None:
            for i in range(40):
                append_event(
                    postgres_url,
                    tenant_id=tenant_b,
                    run_id=run_b.run_id,
                    event_type="assistant.delta",
                    payload={"n": i, "tenant": "B"},
                )
                time.sleep(0.1)

        tenant_b_thread = threading.Thread(target=produce_b, daemon=True)
        tenant_b_thread.start()

        producer = subprocess.Popen(
            [sys.executable, "-c", _PRODUCER],
            env=_child_env(
                {
                    "C02_URL": postgres_url,
                    "C02_TENANT": tenant_a,
                    "C02_RUN": run_a.run_id,
                    "C02_REDIS": REDIS_URL,
                    "C02_STREAM": _STREAM,
                }
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert producer.stdout is not None
        first_line = producer.stdout.readline()
        assert first_line.startswith("PID "), first_line
        reported_pid = int(first_line[4:])
        assert reported_pid == producer.pid

        # First connection: follow until seq >= 10, then simulate the drop.
        seen_a: list[int] = []
        dropped = {"flag": False}

        async def first_connection() -> None:
            async def closed() -> bool:
                return dropped["flag"]

            async for frame in iter_frames(
                postgres_url,
                tenant_id=tenant_a,
                run_id=run_a.run_id,
                after_seq=0,
                redis_client=app.state.redis,
                follow=True,
                is_disconnected=closed,
            ):
                for seq in _frame_seqs(frame):
                    seen_a.append(seq)
                    if seq >= 10:
                        dropped["flag"] = True

        def run_first() -> None:
            asyncio.run(asyncio.wait_for(first_connection(), timeout=30))

        conn1 = threading.Thread(target=run_first, daemon=True)
        conn1.start()
        conn1.join(timeout=35)
        assert not conn1.is_alive()
        last_seen = max(seen_a)

        # Network drop: pause Redis; dispatches fail and rows stay pending.
        paused = _docker("pause", _REDIS)
        assert paused.returncode == 0, paused.stderr
        try:
            # dispatch_pending increments attempts per failed publish and
            # commits when its transaction returns. The producer keeps
            # appending during the outage, so poll until a run-A row is
            # pending with a recorded failed attempt — deterministic even
            # if the producer drained the outbox just before the pause.
            down_client = redis.Redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=0.3,
                socket_connect_timeout=0.3,
            )
            deadline = time.time() + 12
            pending: list = []
            attempts_seen = False
            while time.time() < deadline:
                dispatch_pending(postgres_url, down_client, stream=_STREAM)
                engine = create_engine(postgres_url)
                with Session(engine) as db:
                    pending = db.execute(
                        text(
                            """
                            SELECT o.attempts FROM outbox o
                            JOIN run_events e ON e.event_id = o.event_id
                            WHERE e.run_id = :run AND o.dispatch_status = 'pending'
                            """
                        ),
                        {"run": run_a.run_id},
                    ).all()
                engine.dispose()
                if pending and any(int(row.attempts) > 0 for row in pending):
                    attempts_seen = True
                    break
                time.sleep(0.3)
            assert pending, "no pending outbox rows during the Redis outage"
            assert attempts_seen, (
                "dispatches did not retry against the paused Redis"
            )
        finally:
            unpause = _docker("unpause", _REDIS)
            assert unpause.returncode == 0, unpause.stderr

        # Reconnect through HTTP with Last-Event-ID and read to stream end.
        seen_b: list[int] = []
        with client.stream(
            "GET",
            f"/api/v1/runs/{run_a.run_id}/events?follow=1",
            headers={"Last-Event-ID": str(last_seen)},
            timeout=httpx.Timeout(60.0),
        ) as response:
            assert response.status_code == 200
            body = ""
            for chunk in response.iter_text():
                body += chunk
                seen_b.extend(_frame_seqs(chunk))
        assert '"tenant":"B"' not in body, "tenant B payload leaked into run A stream"

        # Every seq arrives once across both connections, no gaps, no dups.
        engine = create_engine(postgres_url)
        with Session(engine) as db:
            run_row = db.get(Run, run_a.run_id)
            assert run_row is not None
            assert run_row.status == "succeeded"
            assert run_row.status != "cancelled"
            final_seq = int(db.scalar(
                select(RunEvent.seq)
                .where(RunEvent.run_id == run_a.run_id)
                .order_by(RunEvent.seq.desc())
            ))
        engine.dispose()
        combined = seen_a + seen_b
        assert len(combined) == len(set(combined)), "duplicate seq across connections"
        assert sorted(combined) == list(range(1, final_seq + 1)), (
            f"gaps: expected 1..{final_seq}, got {sorted(combined)}"
        )
        assert producer.poll() is None or producer.returncode == 0
        assert reported_pid == producer.pid

        # Flush the outbox; each run-A event lands in the stream exactly once.
        flush_client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
        )
        dispatch_pending(postgres_url, flush_client, stream=_STREAM)
        engine = create_engine(postgres_url)
        with Session(engine) as db:
            rows = db.execute(
                text(
                    """
                    SELECT o.dispatch_status, o.event_id, o.attempts FROM outbox o
                    JOIN run_events e ON e.event_id = o.event_id
                    WHERE e.run_id = :run
                    """
                ),
                {"run": run_a.run_id},
            ).all()
            event_ids = [str(row.event_id) for row in rows]
        engine.dispose()
        assert rows and all(row.dispatch_status == "sent" for row in rows)
        # Redis stream is at-least-once (outbox pattern; a publish that timed
        # out during a pause may still land). Exactly-once delivery to
        # clients is by seq from PostgreSQL — asserted on `seen` above.
        entries = flush_client.xrange(_STREAM)
        run_a_entries = [
            str(fields.get("event_id"))
            for _mid, fields in entries
            if str(fields.get("run_id")) == run_a.run_id
        ]
        assert set(run_a_entries) == set(event_ids)
        duplicates = len(run_a_entries) - len(set(run_a_entries))
        attempted = sum(1 for row in rows if int(row.attempts) > 0)
        assert duplicates <= attempted, (
            f"{duplicates} duplicate stream entries but only "
            f"{attempted} rows ever retried"
        )

        # Tenant B must not read run A at all.
        other_token = uuid.uuid4().hex
        app.state.sessions[_hash_token(SECRET, other_token)] = AuthRecord(
            user_id="user-c02b", tenant_id=tenant_b, created=time.monotonic()
        )
        denied = client.get(
            f"/api/v1/runs/{run_a.run_id}/events",
            cookies={"rxy_session": other_token},
        )
        assert denied.status_code == 404
    finally:
        if producer is not None:
            try:
                producer.wait(timeout=15)
            except subprocess.TimeoutExpired:
                producer.kill()
                producer.wait(timeout=10)
        if tenant_b_thread is not None:
            tenant_b_thread.join(timeout=10)
        _docker("rm", "-f", _REDIS)
