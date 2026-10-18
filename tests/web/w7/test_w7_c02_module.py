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


def _serve_app(app) -> tuple:
    """Boot the real FastAPI app through uvicorn on an ephemeral 127.0.0.1 port.

    Same in-thread pattern as ``devices.gateway.serve_in_thread``: a real
    socket, so a client-side abort produces a real transport disconnect for
    the SSE generator (request.is_disconnected), not a simulated boolean.
    """
    import uvicorn

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    ready = threading.Event()

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def go() -> None:
            task = loop.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.01)
            ready.set()
            await task

        loop.run_until_complete(go())
        loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=15), "uvicorn server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


def test_w7_c02_integration(postgres_url: str):
    """Real-socket SSE: abort mid-run, Redis paused, reconnect — all seqs once."""
    upgrade_head(postgres_url)
    _redis_start()
    producer = None
    tenant_b_thread = None
    server = None
    server_thread = None
    try:
        app = create_app(postgres_url, mode="local", secret=SECRET, allowed_origins=[ORIGIN])
        app.state.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        server, server_thread, port = _serve_app(app)

        # Real HTTP transport end-to-end (login + SSE over the socket).
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=httpx.Timeout(60.0)
        )
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

        # Connection 1: a real streaming HTTP GET on the uvicorn socket,
        # opened while the producer is still appending events. The abort is
        # a real transport disconnect — closing the streaming response
        # drops the TCP connection mid-run (the server's
        # request.is_disconnected then actually reports the drop).
        seen_a: list[int] = []
        body_a: list[str] = []
        events_url = f"/api/v1/runs/{run_a.run_id}/events?follow=1"
        with client.stream("GET", events_url, timeout=httpx.Timeout(60.0)) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                body_a.append(line)
                if line.startswith("id: "):
                    seen_a.append(int(line[4:]))
                    if seen_a[-1] >= 10:
                        break  # abort mid-stream: closing drops the socket
        assert seen_a, "connection 1 collected no seqs before the abort"
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

        # Connection 2: reconnect over a real socket with Last-Event-ID and
        # read to the real stream end (the server stops on terminal status).
        seen_b: list[int] = []
        body_b: list[str] = []
        with client.stream(
            "GET",
            events_url,
            headers={"Last-Event-ID": str(last_seen)},
            timeout=httpx.Timeout(60.0),
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                body_b.append(line)
                if line.startswith("id: "):
                    seen_b.append(int(line[4:]))
        body = "\n".join(body_a + body_b)
        assert '"tenant":"B"' not in body and '"tenant": "B"' not in body, (
            "tenant B payload leaked into run A stream"
        )
        # The abort really did happen mid-run: seqs arrived on connection 1
        # and the rest on connection 2 — both non-empty.
        assert seen_b, "connection 2 collected no seqs after the reconnect"

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
        assert last_seen < final_seq, (
            f"connection 1 aborted at seq {last_seen} but the run ended at "
            f"{final_seq} — the disconnect was not mid-run"
        )
        combined = seen_a + seen_b
        assert len(combined) == len(set(combined)), "duplicate seq across connections"
        assert sorted(combined) == list(range(1, final_seq + 1)), (
            f"gaps: expected 1..{final_seq}, got {sorted(combined)}"
        )
        assert producer.poll() is None or producer.returncode == 0
        assert reported_pid == producer.pid

        # Flush the outbox; each run-A event lands in the stream at least once.
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
        # out during a pause may still land, so a retried row can legitimately
        # appear more than once). Exactly-once delivery to clients is by seq
        # from PostgreSQL — asserted on the seqs above. Per-event provenance:
        # event e must appear at least once and at most
        # dispatch_attempts(e) = attempts(e) + 1 times — the outbox ``attempts``
        # counter records only FAILED publishes, each of which may still have
        # landed, plus the one successful publish that marked the row 'sent'.
        entries = flush_client.xrange(_STREAM)
        run_a_entries = [
            str(fields.get("event_id"))
            for _mid, fields in entries
            if str(fields.get("run_id")) == run_a.run_id
        ]
        assert set(run_a_entries) == set(event_ids)
        for row in rows:
            event_id = str(row.event_id)
            count = run_a_entries.count(event_id)
            dispatch_attempts = int(row.attempts) + 1
            assert 1 <= count <= max(1, dispatch_attempts), (
                f"event {event_id} appears {count}x in the stream but its "
                f"outbox row only records {dispatch_attempts} publish call(s)"
            )

        # Tenant B must not read run A at all.
        other_token = uuid.uuid4().hex
        app.state.sessions[_hash_token(SECRET, other_token)] = AuthRecord(
            user_id="user-c02b", tenant_id=tenant_b, created=time.monotonic()
        )
        denied_client = httpx.Client(
            base_url=client.base_url,
            cookies={"rxy_session": other_token},
            timeout=httpx.Timeout(30.0),
        )
        denied = denied_client.get(f"/api/v1/runs/{run_a.run_id}/events")
        assert denied.status_code == 404
    finally:
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=10)
        if producer is not None:
            try:
                producer.wait(timeout=15)
            except subprocess.TimeoutExpired:
                producer.kill()
                producer.wait(timeout=10)
        if tenant_b_thread is not None:
            tenant_b_thread.join(timeout=10)
        _docker("rm", "-f", _REDIS)
