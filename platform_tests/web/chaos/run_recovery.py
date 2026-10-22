"""WEB-W7-C02 crash/disconnect chaos harness.

Runs seven fault-injection scenarios against fresh rows in the shared
PostgreSQL container and a card-owned Redis container (rxy-w7c02-redis),
then writes a JSON report. Worker crashes are simulated by killing the
exact child PID (proc.kill / TerminateProcess, never a tree kill).

Usage:
    python platform_tests/web/chaos/run_recovery.py \
        --database-url postgresql+psycopg://postgres@127.0.0.1:55432/rxycode \
        --redis-url redis://127.0.0.1:56390/0 \
        --report report.json [--workdir DIR]

Exit code is non-zero when any scenario failed, any marker process
leaked, or a cross-tenant event leaked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _path in (REPO, _SERVER, _WORKER, _RUNNER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import psutil  # noqa: E402
import redis as _redis_lib  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from rxycode_server.approvals.service import decide_approval, list_pending  # noqa: E402
from rxycode_server.events.store import append_event, replay  # noqa: E402
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Project,
    Run,
    SessionRow,
    ToolInvocation,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.queue import dispatch_pending  # noqa: E402
from rxycode_worker.recovery import run_shell_before_ack  # noqa: E402
from rxycode_worker.supervisor import (  # noqa: E402
    LeaseRejected,
    claim,
    commit_terminal,
)

from RxyCode.RxyCode1_1_0.execution.tool_journal import (  # noqa: E402
    ToolExecutionJournal,
)

_PG_CONTAINER = "rxy-w2c01-pg"
_REDIS_CONTAINER = "rxy-w7c02-redis"
_STREAM = "rxycode:w7c02"
_SECRET = "local-web-secret-value-32bytes!!"

_MARKERS: list[str] = []


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=False
    )


def _redis_start(redis_url: str) -> None:
    _docker("rm", "-f", _REDIS_CONTAINER)
    started = _docker(
        "run",
        "-d",
        "--name",
        _REDIS_CONTAINER,
        "-p",
        "127.0.0.1:56390:6379",
        "redis:7",
    )
    if started.returncode != 0:
        raise RuntimeError(f"redis container failed: {started.stderr.strip()}")
    deadline = time.time() + 30
    while time.time() < deadline:
        if _docker("exec", _REDIS_CONTAINER, "redis-cli", "ping").stdout.strip() == "PONG":
            return
        time.sleep(0.5)
    raise RuntimeError("redis did not become ready")


def _redis_cleanup() -> None:
    _docker("rm", "-f", _REDIS_CONTAINER)


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    parts = [str(REPO), str(_SERVER), str(_WORKER), str(_RUNNER)]
    previous = env.get("PYTHONPATH", "")
    if previous:
        parts.append(previous)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _spawn(script: str, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stdout_queue(proc: subprocess.Popen) -> "queue.Queue[str]":
    """Start one pump per process; reuse the queue for every read."""
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    return lines


def _read_queue(lines: "queue.Queue[str]", prefix: str, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = lines.get(timeout=max(0.05, deadline - time.time()))
        except queue.Empty:
            break
        if line.startswith(prefix):
            return line.strip()
    raise AssertionError(f"child did not print {prefix!r} within {timeout}s")


def _read_stdout(proc: subprocess.Popen, prefix: str, timeout: float) -> str:
    return _read_queue(_stdout_queue(proc), prefix, timeout)


def _sse_events(
    lines: Iterable[str], raw: list[str]
) -> Iterator[dict[str, str]]:
    """Yield only COMPLETE SSE events (blank-line terminated).

    Field lines accumulate into a pending frame; the empty line commits
    it. Comment lines (``: open`` heartbeat) are skipped. An abort that
    lands mid-event leaves the partial frame unconsumed — it must never
    count as delivered, so the reconnect cursor comes only from completed
    events. ``raw`` collects every consumed line for the leak check.
    """
    pending: dict[str, str] = {}
    for line in lines:
        raw.append(line)
        if line == "":
            if pending:
                yield pending
            pending = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        pending[field.strip()] = value.lstrip(" ")


def _with_connect_timeout(url: str, seconds: int = 3) -> str:
    """Merge ``connect_timeout`` into a database URL's query string.

    ``url + "?connect_timeout=3"`` corrupts a URL that already carries
    parameters — ``?sslmode=disable?connect_timeout=3`` makes psycopg read
    the second ``?`` as part of the sslmode value, so the timeout silently
    never applies. Parse and re-encode instead: an existing query gets
    ``&connect_timeout=N``, a bare URL gets ``?connect_timeout=N``.
    """
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "connect_timeout"
    ]
    query.append(("connect_timeout", str(seconds)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _serve_app(app) -> tuple:
    """Boot the real FastAPI app through uvicorn on an ephemeral loopback port.

    A real socket means a client-side abort is a real transport disconnect
    for the SSE generator (``request.is_disconnected`` actually reports the
    drop) — not a simulated boolean. Same in-thread pattern as
    ``devices.gateway.serve_in_thread``.
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


def _run_child(
    script: str, env: dict[str, str], prefix: str, timeout: float = 120
) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"child exited {proc.returncode}: {proc.stdout[-2000:]}")
    line = next(
        (item for item in proc.stdout.splitlines() if item.startswith(prefix)),
        None,
    )
    if line is None:
        raise AssertionError(f"child printed no {prefix!r} line: {proc.stdout[-2000:]}")
    return json.loads(line.removeprefix(prefix))


def _seed(database_url: str, tag: str, permission_profile: str):
    # The shared chaos DB keeps rows from earlier runs, so every id is
    # namespaced with a fresh suffix — the harness must be re-runnable.
    tag = f"{tag}-{uuid.uuid4().hex[:8]}"
    engine = create_engine(database_url)
    session_id = uuid.uuid4().hex
    tenant = f"tenant-chaos-{tag}"
    with Session(engine) as db:
        db.add(User(id=f"user-{tag}", github_id=f"gh-{tag}", kind="github"))
        db.add(Organization(id=f"org-{tag}", tenant_id=tenant))
        db.add(
            Project(id=f"project-{tag}", tenant_id=tenant, name="app", repo_config={})
        )
        db.add(
            SessionRow(
                id=session_id,
                tenant_id=tenant,
                project_id=f"project-{tag}",
                title=tag,
            )
        )
        db.commit()
    engine.dispose()
    run = create_run(
        database_url,
        tenant_id=tenant,
        session_id=session_id,
        message=f"chaos {tag}",
        target_id=f"local:{tag}",
        permission_profile=permission_profile,
        request_id=f"req-chaos-{tag}",
    )
    return tenant, run


def _marker_procs(marker: str, ignore_pid: int | None = None) -> list[dict]:
    hits: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
        if proc.info["pid"] in {os.getpid(), ignore_pid}:
            continue
        try:
            cmdline = proc.info["cmdline"] or []
            if any(marker in arg for arg in cmdline):
                hits.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return hits


def _kill_marked(marker: str) -> int:
    killed = 0
    for info in _marker_procs(marker):
        try:
            psutil.Process(info["pid"]).kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


_PAUSE_WORKER = """\
import os, time
from datetime import datetime, timedelta, timezone
from rxycode_worker.supervisor import claim
from rxycode_worker.interrupt_resume import pause_for_approval

url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(url, run_id, os.environ["C02_WORKER"], ttl_seconds=30)
paused = pause_for_approval(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    tool="bash",
    permission_scope="workspace-write",
    arguments={"command": os.environ["C02_COMMAND"]},
    deadline=datetime.now(timezone.utc) + timedelta(hours=4),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
    journal_dir=os.environ["C02_JOURNAL"],
    workdir=os.environ["C02_WORKDIR"],
    command=os.environ["C02_COMMAND"],
)
print("PAUSED " + str(paused["approval_id"]), flush=True)
time.sleep(120)
"""

_RESUME_WORKER = """\
import json, os
from rxycode_worker.interrupt_resume import resume_approved
result = resume_approved(
    os.environ["C02_URL"],
    tenant_id=os.environ["C02_TENANT"],
    run_id=os.environ["C02_RUN"],
    approval_id=os.environ["C02_APPROVAL"],
    worker_id=os.environ["C02_WORKER"],
    journal_dir=os.environ["C02_JOURNAL"],
    workdir=os.environ["C02_WORKDIR"],
    command=os.environ["C02_COMMAND"],
)
print("RESUMED " + json.dumps(result, default=str), flush=True)
"""

_SHELL_WORKER = """\
import json, os
from rxycode_worker.supervisor import claim
from rxycode_worker.recovery import run_shell_before_ack
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(
    url, run_id, os.environ["C02_WORKER"],
    ttl_seconds=int(os.environ["C02_TTL"]),
)
result = run_shell_before_ack(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    attempt_id=os.environ["C02_ATTEMPT"],
    command=os.environ["C02_COMMAND"],
    workdir=os.environ["C02_WORKDIR"],
    journal=ToolExecutionJournal(os.environ["C02_JOURNAL"]),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
)
print("RESULT " + json.dumps(result, default=str), flush=True)
"""

_RECOVER_WORKER = """\
import json, os
from rxycode_worker.supervisor import claim
from rxycode_worker.recovery import recover_unknown_shell
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(url, run_id, os.environ["C02_WORKER"], ttl_seconds=60)
result = recover_unknown_shell(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    attempt_id=os.environ["C02_ATTEMPT"],
    command=os.environ["C02_COMMAND"],
    workdir=os.environ["C02_WORKDIR"],
    journal=ToolExecutionJournal(os.environ["C02_JOURNAL"]),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
)
print("RECOVERED " + json.dumps(result, default=str), flush=True)
"""

_PGDOWN_WORKER = """\
import json, os, time
from sqlalchemy import create_engine, text
from rxycode_worker.supervisor import renew_lease
from rxycode_worker.recovery import run_shell_before_ack
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
worker = os.environ["C02_WORKER"]
epoch = int(os.environ["C02_EPOCH"])
print("READY", flush=True)
# Barrier: the parent pauses Postgres first, then drops the GO file —
# every call below lands strictly inside the outage window.
go = os.environ["C02_GOFILE"]
deadline = time.time() + 60
while not os.path.exists(go):
    if time.time() > deadline:
        raise SystemExit("GO file never arrived")
    time.sleep(0.05)
exec_error = None
result = None
try:
    result = run_shell_before_ack(
        url,
        tenant_id=os.environ["C02_TENANT"],
        run_id=run_id,
        call_id=os.environ["C02_CALL"],
        attempt_id=os.environ["C02_ATTEMPT"],
        command=os.environ["C02_COMMAND"],
        workdir=os.environ["C02_WORKDIR"],
        journal=ToolExecutionJournal(os.environ["C02_JOURNAL"]),
        worker_id=worker,
        epoch=epoch,
    )
except Exception as exc:
    exec_error = type(exc).__name__
probe_error = None
try:
    probe = create_engine(url)
    try:
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        probe.dispose()
except Exception as exc:
    probe_error = type(exc).__name__
renew_error = None
try:
    renew_lease(url, run_id, worker, epoch, ttl_seconds=30)
except Exception as exc:
    renew_error = type(exc).__name__
out = {
    "executed": bool(result and result.get("executed")),
    "exec_error": exec_error,
    "exec_status": (result or {}).get("run_status"),
    "probe_error": probe_error,
    "renew_error": renew_error,
    "result": result,
}
print("PGDOWN " + json.dumps(out, default=str), flush=True)
"""


def scenario_worker_kill_during_approval(url: str, workdir: Path) -> dict:
    """Approval survives a worker kill; it executes exactly once after approve."""
    tenant, run = _seed(url, "s1", "confirm_all")
    wd = Path(tempfile.mkdtemp(prefix="w7c02-s1-", dir=workdir))
    journal_dir = Path(tempfile.mkdtemp(prefix="w7c02-s1j-", dir=workdir))
    exe = "python" if os.name == "nt" else "python3"
    command = (
        f"{exe} -c \"from pathlib import Path; Path('c02-approve.txt').write_text('once', encoding='utf-8')\""
    )
    target = wd / "c02-approve.txt"
    base_env = {
        "C02_URL": url,
        "C02_TENANT": tenant,
        "C02_RUN": run.run_id,
        "C02_CALL": "call_" + uuid.uuid4().hex,
        "C02_JOURNAL": str(journal_dir),
        "C02_WORKDIR": str(wd),
        "C02_COMMAND": command,
    }
    proc = _spawn(_PAUSE_WORKER, _child_env({**base_env, "C02_WORKER": "w-s1a"}))
    try:
        approval_id = _read_stdout(proc, "PAUSED ", 90).removeprefix("PAUSED ")
    finally:
        proc.kill()
        proc.wait(timeout=15)

    engine = create_engine(url)
    with Session(engine) as db:
        row = db.get(Run, run.run_id)
        assert row is not None
        assert row.status == "waiting_approval", row.status
        assert row.lease_owner is None
    engine.dispose()
    pending = list_pending(url, tenant_id=tenant, run_id=run.run_id)
    assert [item["approval_id"] for item in pending] == [approval_id]
    assert pending[0]["tool"] == "bash"
    assert pending[0]["permission_scope"] == "workspace-write"
    assert pending[0]["arguments"]["command"] == command
    assert not target.exists()

    decided = decide_approval(
        url,
        tenant_id=tenant,
        approval_id=approval_id,
        decision="approved",
        expected_revision=0,
        now=datetime.now(timezone.utc),
    )
    assert decided["status"] == "approved"
    first = _run_child(
        _RESUME_WORKER,
        _child_env(
            {**base_env, "C02_WORKER": "w-s1b", "C02_APPROVAL": approval_id}
        ),
        "RESUMED ",
    )
    assert first["executed"] is True, first
    assert target.read_text(encoding="utf-8").count("once") == 1
    again = _run_child(
        _RESUME_WORKER,
        _child_env(
            {**base_env, "C02_WORKER": "w-s1c", "C02_APPROVAL": approval_id}
        ),
        "RESUMED ",
    )
    assert again["executed"] is False
    assert target.read_text(encoding="utf-8").count("once") == 1
    engine = create_engine(url)
    with Session(engine) as db:
        done = db.get(Run, run.run_id)
        assert done is not None and done.status == "succeeded"
    engine.dispose()
    return {
        "name": "worker_kill_during_approval",
        "outcome": "correct",
        "details": f"approval {approval_id} survived the kill; one write in {target.name}",
    }


def scenario_worker_kill_after_side_effect(url: str, workdir: Path) -> dict:
    """Side effect landed, ACK was lost with the worker: unknown, never replayed."""
    tenant, run = _seed(url, "s2", "full_auto")
    wd = Path(tempfile.mkdtemp(prefix="w7c02-s2-", dir=workdir))
    journal_dir = Path(tempfile.mkdtemp(prefix="w7c02-s2j-", dir=workdir))
    marker = f"c02marker-s2-{uuid.uuid4().hex[:8]}"
    _MARKERS.append(marker)
    exe = "python" if os.name == "nt" else "python3"
    command = (
        f"{exe} -c \"from pathlib import Path; Path('c02-side.txt').write_text('once', encoding='utf-8')\"; "
        f"sleep 30 # {marker}"
    )
    target = wd / "c02-side.txt"
    call_id = "call_" + uuid.uuid4().hex
    attempt_id = "att_" + uuid.uuid4().hex
    base_env = {
        "C02_URL": url,
        "C02_TENANT": tenant,
        "C02_RUN": run.run_id,
        "C02_CALL": call_id,
        "C02_ATTEMPT": attempt_id,
        "C02_JOURNAL": str(journal_dir),
        "C02_WORKDIR": str(wd),
        "C02_COMMAND": command,
        "C02_TTL": "3",
    }
    leaked: list[dict] = []
    try:
        proc = _spawn(
            _SHELL_WORKER, _child_env({**base_env, "C02_WORKER": "w-s2a"})
        )
        deadline = time.time() + 60
        while time.time() < deadline and not target.exists():
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout is not None else ""
                raise AssertionError(
                    f"worker exited before the side effect: {out[-2000:]}"
                )
            time.sleep(0.2)
        assert target.exists()
        proc.kill()
        proc.wait(timeout=15)

        time.sleep(4.5)
        recovered = _run_child(
            _RECOVER_WORKER,
            _child_env({**base_env, "C02_WORKER": "w-s2b"}),
            "RECOVERED ",
        )
        assert recovered["executed"] is False, recovered
        assert recovered["run_status"] == "recovery_required", recovered
        assert target.read_text(encoding="utf-8").count("once") == 1

        engine = create_engine(url)
        with Session(engine) as db:
            rows = db.scalars(
                select(ToolInvocation).where(ToolInvocation.run_id == run.run_id)
            ).all()
        engine.dispose()
        matched = [row for row in rows if row.call_id == call_id]
        assert len(matched) == 1 and matched[0].journal_state == "unknown"

        second = _run_child(
            _RECOVER_WORKER,
            _child_env({**base_env, "C02_WORKER": "w-s2c"}),
            "RECOVERED ",
        )
        assert second["executed"] is False
        assert target.read_text(encoding="utf-8").count("once") == 1

        deadline = time.time() + 10
        while time.time() < deadline:
            leaked = _marker_procs(marker, ignore_pid=proc.pid)
            if not leaked:
                break
            time.sleep(0.5)
        leaked = _marker_procs(marker, ignore_pid=proc.pid)
        if leaked:
            return {
                "name": "worker_kill_after_side_effect",
                "outcome": "failed",
                "details": f"orphaned shell survived the worker kill: {leaked}",
            }
        return {
            "name": "worker_kill_after_side_effect",
            "outcome": "unknown",
            "details": (
                "journal_state=unknown, recovery_required, exactly one write, "
                "no leaked shell"
            ),
        }
    finally:
        _kill_marked(marker)


def scenario_redis_down_after_commit(url: str, redis_url: str, workdir: Path) -> dict:
    """PG keeps the committed event; the outbox survives a Redis outage."""
    tenant, run = _seed(url, "s3", "workspace-write")
    seq = append_event(
        url,
        tenant_id=tenant,
        run_id=run.run_id,
        event_type="assistant.delta",
        payload={"n": 0, "tenant": "A"},
    )
    paused = _docker("pause", _REDIS_CONTAINER)
    assert paused.returncode == 0, paused.stderr
    try:
        # PG replay delivers the committed event without Redis — the
        # client-visible exactly-once path, by seq.
        result = replay(url, tenant_id=tenant, run_id=run.run_id, after_seq=0)
        assert result["code"] is None
        seqs = [item["seq"] for item in result["events"]]
        assert seqs == sorted(set(seqs)), f"duplicate seqs in PG replay: {seqs}"
        assert seq in seqs
        # A dispatch against the dead broker stays pending with attempts.
        down_client = _redis_lib.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=0.3,
            socket_connect_timeout=0.3,
        )
        dispatch_pending(url, down_client, stream=_STREAM)
        engine = create_engine(url)
        with Session(engine) as db:
            pending = db.execute(
                text(
                    """
                    SELECT o.attempts FROM outbox o
                    JOIN run_events e ON e.event_id = o.event_id
                    WHERE e.run_id = :run AND o.dispatch_status = 'pending'
                    """
                ),
                {"run": run.run_id},
            ).all()
        engine.dispose()
        assert pending, "outbox row vanished during the Redis outage"
        assert any(int(row.attempts) > 0 for row in pending)
    finally:
        unpaused = _docker("unpause", _REDIS_CONTAINER)
        assert unpaused.returncode == 0, unpaused.stderr

    client = _redis_lib.Redis.from_url(
        redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
    )
    dispatch_pending(url, client, stream=_STREAM)
    engine = create_engine(url)
    with Session(engine) as db:
        rows = db.execute(
            text(
                """
                SELECT o.dispatch_status, o.event_id, o.attempts FROM outbox o
                JOIN run_events e ON e.event_id = o.event_id
                WHERE e.run_id = :run
                """
            ),
            {"run": run.run_id},
        ).all()
    engine.dispose()
    assert rows and all(row.dispatch_status == "sent" for row in rows)
    # Redis stream is at-least-once (outbox pattern; a publish that timed
    # out during a pause may still land). Exactly-once delivery to clients
    # is by seq from PostgreSQL. Per-event provenance bound: the outbox
    # ``attempts`` counter records only FAILED publishes, each of which may
    # still have landed, plus the one successful publish that marked the
    # row 'sent' — so event e may appear at most attempts(e) + 1 times.
    entries = client.xrange(_STREAM)
    streamed = [str(fields.get("event_id")) for _mid, fields in entries]
    duplicates = 0
    for row in rows:
        n = streamed.count(str(row.event_id))
        dispatch_attempts = int(row.attempts) + 1
        assert 1 <= n <= max(1, dispatch_attempts), (
            f"event {row.event_id} appears {n}x in the stream but its "
            f"outbox row only records {dispatch_attempts} publish call(s)"
        )
        duplicates += n - 1
    return {
        "name": "redis_down_after_commit",
        "outcome": "correct",
        "details": (
            f"seq {seq} replayed from PG once; outbox pending then sent; "
            f"stream duplicates={duplicates} (at-least-once)"
        ),
    }


def scenario_sse_disconnect_reconnect(url: str, redis_url: str) -> dict:
    """Real-socket SSE: mid-run abort, Last-Event-ID resume, all seqs once.

    Two real HTTP streaming connections against a real uvicorn server. The
    first socket is closed while the producer is still appending events —
    a real TCP disconnect, not a simulated flag — and the second resumes
    with Last-Event-ID. Every seq must arrive exactly once, in order,
    and the run must still reach its terminal status.
    """
    import httpx

    from rxycode_server.api.auth import AuthRecord, _hash_token
    from rxycode_server.main import create_app

    tenant, run = _seed(url, "s4", "workspace-write")
    tenant_b, run_b = _seed(url, "s4b", "workspace-write")

    app = create_app(
        url, mode="local", secret=_SECRET, allowed_origins=["http://127.0.0.1"]
    )
    # create_app keeps browser sessions in the database. This scenario
    # still injects cookies into the per-process dict the lookup checks first.
    app.state.sessions = {}
    app.state.redis = _redis_lib.Redis.from_url(redis_url, decode_responses=True)
    server, server_thread, port = _serve_app(app)

    produced_b = threading.Event()

    def produce_a() -> None:
        epoch = claim(url, run.run_id, "w-s4", ttl_seconds=30)
        for i in range(24):
            append_event(
                url,
                tenant_id=tenant,
                run_id=run.run_id,
                event_type="assistant.delta",
                payload={"n": i, "tenant": "A"},
            )
            time.sleep(0.2)
        commit_terminal(url, run.run_id, "w-s4", epoch, "succeeded")

    def produce_b() -> None:
        for i in range(24):
            append_event(
                url,
                tenant_id=tenant_b,
                run_id=run_b.run_id,
                event_type="assistant.delta",
                payload={"n": i, "tenant": "B"},
            )
            produced_b.set()
            time.sleep(0.1)

    thread_a = threading.Thread(target=produce_a, daemon=True)
    thread_b = threading.Thread(target=produce_b, daemon=True)

    token_a = uuid.uuid4().hex
    app.state.sessions[_hash_token(_SECRET, token_a)] = AuthRecord(
        user_id="user-s4", tenant_id=tenant, created=time.monotonic()
    )
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        cookies={"rxy_session": token_a},
        timeout=httpx.Timeout(60.0),
    )
    events_a: list[dict[str, str]] = []
    events_b: list[dict[str, str]] = []
    body_parts: list[str] = []
    last_seen = 0
    final_seq = 0
    cross_leak = False
    try:
        thread_a.start()
        thread_b.start()
        events_url = f"/api/v1/runs/{run.run_id}/events?follow=1"
        # Connection 1: real streaming GET while the producer is still
        # appending; breaking out closes the response and drops the TCP
        # connection mid-run. Only COMPLETE events (blank-line terminated)
        # count — a partially consumed frame must never advance the cursor.
        with client.stream("GET", events_url) as response:
            assert response.status_code == 200
            line_iter = iter(response.iter_lines())
            for event in _sse_events(line_iter, body_parts):
                events_a.append(event)
                if int(event.get("id", "0")) >= 4:
                    # Abort mid-event: consume the next frame's first line
                    # (its id:) without the data: payload, then drop the
                    # socket. The half-read event is not delivered; the
                    # resume must re-deliver it.
                    extra = next(line_iter, None)
                    if extra is not None:
                        body_parts.append(extra)
                    break
        seen_a = [int(event["id"]) for event in events_a if "id" in event]
        assert seen_a, "connection 1 collected no seqs before the abort"
        last_seen = seen_a[-1]

        # Connection 2: reconnect with Last-Event-ID and read to the real
        # stream end — the server stops once the run is terminal and no
        # new frames remain.
        with client.stream(
            "GET", events_url, headers={"Last-Event-ID": str(last_seen)}
        ) as response:
            assert response.status_code == 200
            for event in _sse_events(response.iter_lines(), body_parts):
                events_b.append(event)
        seen_b = [int(event["id"]) for event in events_b if "id" in event]
        assert seen_b, "connection 2 collected no seqs after the reconnect"

        engine = create_engine(url)
        with Session(engine) as db:
            row = db.get(Run, run.run_id)
            assert row is not None and row.status == "succeeded"
            assert row.status != "cancelled"
            final_seq = int(row.event_seq or 0)
        engine.dispose()
        assert last_seen < final_seq, (
            f"connection 1 aborted at seq {last_seen} but the run ended "
            f"at {final_seq} — the disconnect was not mid-run"
        )
        # Payload-level exactly-once: seqs come from the consumed `data:`
        # JSON of COMPLETE events only — the partially consumed frame on
        # connection 1 (its `id:` line read, `data:` never delivered) is
        # not in this set and must have been re-delivered by the resume.
        received = [
            int(json.loads(event["data"])["seq"])
            for event in events_a + events_b
            if "id" in event and "data" in event
        ]
        assert len(received) == len(set(received)), (
            "duplicate payload across reconnect"
        )
        assert sorted(received) == list(range(1, final_seq + 1)), (
            f"gaps: expected 1..{final_seq}, got {sorted(received)}"
        )
        body = "\n".join(body_parts)
        cross_leak = '"tenant": "B"' in body or '"tenant":"B"' in body
        assert not cross_leak, "tenant B payload leaked into run A stream"
        assert produced_b.is_set(), (
            "tenant B produced nothing — the leak check was vacuous"
        )

        # Tenant B cannot read run A at all: tenant-scoped replay is 404.
        token_b = uuid.uuid4().hex
        app.state.sessions[_hash_token(_SECRET, token_b)] = AuthRecord(
            user_id="user-s4b", tenant_id=tenant_b, created=time.monotonic()
        )
        denied = httpx.get(
            f"http://127.0.0.1:{port}/api/v1/runs/{run.run_id}/events",
            cookies={"rxy_session": token_b},
            timeout=10,
        )
        assert denied.status_code == 404, denied.status_code
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        thread_a.join(timeout=20)
        thread_b.join(timeout=20)
        client.close()
    return {
        "name": "sse_disconnect_reconnect",
        "outcome": "correct",
        "details": (
            f"real-socket abort at seq {last_seen} of {final_seq}; "
            "Last-Event-ID resume delivered every seq once; "
            f"run status succeeded; cross_tenant_frame={cross_leak}; "
            "tenant B denied"
        ),
        "cross_tenant_leak": cross_leak,
    }


def scenario_stale_lease_after_pause(url: str, workdir: Path) -> dict:
    """A silent worker's stale epoch cannot commit or execute afterwards."""
    tenant, run = _seed(url, "s5", "full_auto")
    wd = Path(tempfile.mkdtemp(prefix="w7c02-s5-", dir=workdir))
    journal_dir = Path(tempfile.mkdtemp(prefix="w7c02-s5j-", dir=workdir))
    epoch1 = claim(url, run.run_id, "w-s5a", ttl_seconds=2)
    assert epoch1 == 1
    time.sleep(3)
    epoch2 = claim(url, run.run_id, "w-s5b", ttl_seconds=30)
    assert epoch2 == 2

    commit_error = None
    try:
        commit_terminal(url, run.run_id, "w-s5a", epoch1, "succeeded")
    except LeaseRejected as exc:
        commit_error = exc
    assert commit_error is not None, "stale epoch committed a terminal status"

    result = None
    exec_error = None
    try:
        result = run_shell_before_ack(
            url,
            tenant_id=tenant,
            run_id=run.run_id,
            call_id="call_" + uuid.uuid4().hex,
            attempt_id="att_" + uuid.uuid4().hex,
            command="Add-Content -LiteralPath 's5.txt' -Value 'x' -Encoding utf8",
            workdir=str(wd),
            journal=ToolExecutionJournal(str(journal_dir)),
            worker_id="w-s5a",
            epoch=epoch1,
        )
    except LeaseRejected as exc:
        exec_error = exc
    assert not (wd / "s5.txt").exists()
    rejected = (
        exec_error is not None
        or (result is not None and result.get("run_status") == "lease_rejected")
    )
    assert rejected and (result is None or result.get("executed") is False)
    return {
        "name": "stale_lease_after_pause",
        "outcome": "correct",
        "details": "stale epoch rejected on commit_terminal and run_shell_before_ack",
    }


def scenario_postgres_unreachable(url: str, workdir: Path) -> dict:
    """PG paused mid-flight: calls fail closed, nothing executes, epoch fenced."""
    tenant, run = _seed(url, "s6", "full_auto")
    wd = Path(tempfile.mkdtemp(prefix="w7c02-s6-", dir=workdir))
    journal_dir = Path(tempfile.mkdtemp(prefix="w7c02-s6j-", dir=workdir))
    target = wd / "s6.txt"
    epoch1 = claim(url, run.run_id, "w-s6a", ttl_seconds=4)
    assert epoch1 == 1
    go_dir = Path(tempfile.mkdtemp(prefix="w7c02-s6g-", dir=workdir))
    go_file = go_dir / "go.signal"
    env = _child_env(
        {
            # ~3 s psycopg connect timeout on the first connection path so
            # calls fail fast instead of hanging through the pause. Merged
            # as a real query parameter — a raw "?" append corrupts URLs
            # that already carry parameters (…?a=b?connect_timeout=3 →
            # psycopg reads it as part of the previous value: no timeout).
            "C02_URL": _with_connect_timeout(url),
            "C02_TENANT": tenant,
            "C02_RUN": run.run_id,
            "C02_WORKER": "w-s6a",
            "C02_EPOCH": str(epoch1),
            "C02_CALL": "call_" + uuid.uuid4().hex,
            "C02_ATTEMPT": "att_" + uuid.uuid4().hex,
            "C02_JOURNAL": str(journal_dir),
            "C02_WORKDIR": str(wd),
            "C02_GOFILE": str(go_file),
            "C02_COMMAND": (
                "Add-Content -LiteralPath 's6.txt' -Value 'x' -Encoding utf8"
            ),
        }
    )
    proc = _spawn(_PGDOWN_WORKER, env)
    lines = _stdout_queue(proc)
    # READY means the child is parked on the GO barrier; pausing first and
    # signalling after puts every one of its calls strictly inside the
    # outage window.
    _read_queue(lines, "READY", 60)
    paused = _docker("pause", _PG_CONTAINER)
    assert paused.returncode == 0, paused.stderr
    try:
        go_file.write_text("go", encoding="utf-8")
        # At least one call must demonstrably fail while Postgres is still
        # paused — assert the specific connectivity failure type, not just
        # any error, before unpausing.
        result = _read_queue(lines, "PGDOWN ", 60)
        out = json.loads(result.removeprefix("PGDOWN "))
        assert out["probe_error"] == "OperationalError", out
        assert out["renew_error"] == "OperationalError", out
        assert out["exec_error"] is None, out
        assert out["exec_status"] == "lease_rejected", out
        assert out["executed"] is False, out
    finally:
        unpaused = _docker("unpause", _PG_CONTAINER)
        assert unpaused.returncode == 0, unpaused.stderr
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass
    assert not target.exists()

    epoch2 = claim(url, run.run_id, "w-s6b", ttl_seconds=30)
    assert epoch2 == 2
    commit_error = None
    try:
        commit_terminal(url, run.run_id, "w-s6a", epoch1, "succeeded")
    except LeaseRejected as exc:
        commit_error = exc
    assert commit_error is not None
    return {
        "name": "postgres_unreachable",
        "outcome": "correct",
        "details": (
            f"exec={out['exec_error'] or out['exec_status']}; "
            f"probe={out['probe_error']}; renew={out['renew_error']}; "
            "old epoch cannot commit"
        ),
    }


def scenario_runner_disconnect_replay(workdir: Path) -> dict:
    """call_id dedup: a dropped device call replays chunks, executes once."""
    import httpx
    from click.testing import CliRunner

    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import request_stop, reset_stop
    from rxycode_runner.transport.tool_rpc import CHUNK_LIMIT, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.supervisor import attempt_tool, resume_device_tool

    body = "你" * 5000
    note = workdir / f"chaos7-{uuid.uuid4().hex[:8]}.txt"
    gateway = serve_in_thread(secret=_SECRET)
    reset_stop()
    browser = gateway.browser_session("tenant-chaos7")
    csrf = "csrf-token-value-for-chaos7"
    issued = httpx.post(
        f"{gateway.http}/api/v1/devices/pairings",
        headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
        cookies={"rxy_session": browser, "rxy_csrf": csrf},
        timeout=5,
    )
    code = issued.json()["code"]
    thread = threading.Thread(
        target=lambda: CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,
                "--code",
                code,
                "--device-id",
                "chaos-dev",
                "--os-name",
                "Windows",
                "--capability",
                "click",
                "--heartbeat-seconds",
                "0.2",
            ],
        ),
        daemon=True,
    )
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not gateway.session_id("chaos-dev"):
        time.sleep(0.05)
    attempt_id = f"att_{uuid.uuid4().hex}"
    call_id = f"call_{uuid.uuid4().hex}"
    try:
        assert gateway.session_id("chaos-dev")
        partial = attempt_tool(
            None,
            attempt_id,
            "write",
            {"path": str(note), "text": "hello-once", "body": body},
            None,
            gateway=gateway,
            device_id="chaos-dev",
            call_id=call_id,
            ack=False,
            stop_after_chunks=2,
        )
        assert [item[0] for item in partial["chunks"]] == [1, 2]
        first_session = gateway.session_id("chaos-dev")
        gateway.drop()
        second_session = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            second_session = gateway.session_id("chaos-dev")
            if second_session and second_session != first_session:
                break
            time.sleep(0.05)
        assert second_session and second_session != first_session
        resumed = resume_device_tool(
            gateway=gateway,
            device_id="chaos-dev",
            call_id=call_id,
            attempt_id=attempt_id,
            resume_from=2,
        )
        seqs = [item[0] for item in resumed.chunks]
        assert seqs and len(seqs) == len(set(seqs))
        assert all(seq > 2 for seq in seqs)
        merged: dict[int, str] = {}
        for seq, data in partial["chunks"] + resumed.chunks:
            merged.setdefault(seq, data)
        replayed = "".join(merged[seq] for seq in sorted(merged))
        assert replayed == body or resumed.truncated
        assert all(len(item.encode("utf-8")) <= CHUNK_LIMIT for item in merged.values())
        assert note.read_text(encoding="utf-8") == "hello-once"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("chaos-dev")
    return {
        "name": "runner_disconnect_replay",
        "outcome": "correct",
        "details": "same call_id replayed stored chunks; write executed once",
    }


def run_all(database_url: str, redis_url: str, workdir: Path | str) -> dict:
    # The bash sandbox rejects workdirs outside execution.workspace_root
    # (the repo checkout), so scenario scratch must live under REPO.
    base = Path(workdir)
    try:
        base.resolve().relative_to(REPO.resolve())
    except ValueError:
        base = REPO
    scratch = base / f".w7c02-chaos-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True, exist_ok=True)
    upgrade_head(database_url)
    scenarios: list[dict] = []
    cross_tenant_leak = False

    def guard(name: str, fn) -> dict:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - record, don't abort the suite
            return {"name": name, "outcome": "failed", "details": f"{type(exc).__name__}: {exc}"}

    _redis_start(redis_url)
    try:
        scenarios.append(
            guard(
                "worker_kill_during_approval",
                lambda: scenario_worker_kill_during_approval(database_url, scratch),
            )
        )
        scenarios.append(
            guard(
                "worker_kill_after_side_effect",
                lambda: scenario_worker_kill_after_side_effect(database_url, scratch),
            )
        )
        scenarios.append(
            guard(
                "redis_down_after_commit",
                lambda: scenario_redis_down_after_commit(
                    database_url, redis_url, scratch
                ),
            )
        )
        s4 = guard(
            "sse_disconnect_reconnect",
            lambda: scenario_sse_disconnect_reconnect(database_url, redis_url),
        )
        if s4.pop("cross_tenant_leak", False):
            cross_tenant_leak = True
        scenarios.append(s4)
        scenarios.append(
            guard(
                "stale_lease_after_pause",
                lambda: scenario_stale_lease_after_pause(database_url, scratch),
            )
        )
        scenarios.append(
            guard(
                "postgres_unreachable",
                lambda: scenario_postgres_unreachable(database_url, scratch),
            )
        )
        try:
            scenarios.append(scenario_runner_disconnect_replay(scratch))
        except ImportError as exc:
            scenarios.append(
                {
                    "name": "runner_disconnect_replay",
                    "outcome": "blocked",
                    "details": f"infrastructure unavailable: {exc}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            scenarios.append(
                {
                    "name": "runner_disconnect_replay",
                    "outcome": "failed",
                    "details": f"{type(exc).__name__}: {exc}",
                }
            )
    finally:
        _redis_cleanup()
        shutil.rmtree(scratch, ignore_errors=True)

    process_leak = 0
    for marker in _MARKERS:
        leaked = _marker_procs(marker)
        if leaked:
            process_leak += len(leaked)
            _kill_marked(marker)

    counts = {"correct": 0, "unknown": 0, "failed": 0, "blocked": 0}
    for item in scenarios:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    return {
        "scenarios": scenarios,
        "counts": counts,
        "process_leak": process_leak,
        "cross_tenant_leak": cross_tenant_leak,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()
    workdir = Path(args.workdir) if args.workdir else REPO
    report = run_all(args.database_url, args.redis_url, workdir)
    Path(args.report).write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for item in report["scenarios"]:
        print(f"{item['outcome']:>8}  {item['name']}: {item['details']}")
    print("counts:", report["counts"])
    print("process_leak:", report["process_leak"])
    print("cross_tenant_leak:", report["cross_tenant_leak"])
    failed = (
        report["counts"].get("failed", 0)
        + report["process_leak"]
        + (1 if report["cross_tenant_leak"] else 0)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
