"""WEB-W2-C03. Two workers race for one lease, and a failed publish does not fork the Run."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (_SERVER, _WORKER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import Organization, Project, SessionRow, User
from rxycode_server.runs.service import create_run
from rxycode_worker.queue import dispatch_pending
from rxycode_worker.supervisor import attempt_tool, claim

_REDIS = "rxy-w2c03-redis"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False)


def _redis_url() -> str:
    _docker("rm", "-f", _REDIS)
    started = _docker(
        "run",
        "-d",
        "--name",
        _REDIS,
        "-p",
        "127.0.0.1:56379:6379",
        "redis:7",
    )
    assert started.returncode == 0, started.stderr
    deadline = time.time() + 30
    while time.time() < deadline:
        ping = _docker("exec", _REDIS, "redis-cli", "ping")
        if ping.stdout.strip() == "PONG":
            return "redis://127.0.0.1:56379/0"
        time.sleep(0.5)
    raise RuntimeError("redis did not become ready")


def _seed(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-mod", github_id="gh-mod", kind="github"))
        db.add(Organization(id="org-mod", tenant_id="tenant-mod"))
        db.add(Project(id="project-mod", tenant_id="tenant-mod", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-mod",
                project_id="project-mod",
                title="run",
            )
        )
        db.commit()
    engine.dispose()
    return session_id


def test_w2_c03_integration(postgres_url: str, tmp_path: Path):
    """One of two racing workers owns the lease, and a dropped publish stays one Run."""
    redis_url = _redis_url()
    session_id = _seed(postgres_url)
    created = create_run(
        postgres_url,
        tenant_id="tenant-mod",
        session_id=session_id,
        message="race",
        target_id="local:1",
        permission_profile="workspace-write",
        request_id="req-race",
    )

    class Boom:
        def xadd(self, *_args, **_kwargs):
            raise ConnectionError("network down")

    assert dispatch_pending(postgres_url, Boom(), stream="rxycode:runs") == 0
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        pending, attempts, runs = conn.execute(
            text(
                "SELECT o.dispatch_status, o.attempts, "
                "(SELECT count(*) FROM runs) FROM outbox o"
            )
        ).one()
    engine.dispose()
    assert pending == "pending"
    assert attempts == 1
    assert runs == 1

    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    assert dispatch_pending(postgres_url, client, stream="rxycode:runs") == 1
    assert dispatch_pending(postgres_url, client, stream="rxycode:runs") == 0
    entries = client.xrange("rxycode:runs")
    assert len(entries) == 1
    assert entries[0][1]["run_id"] == created.run_id

    barrier = threading.Barrier(2)
    found: list[int | None] = []

    def race(worker_id: str) -> None:
        barrier.wait()
        found.append(claim(postgres_url, created.run_id, worker_id))

    threads = [
        threading.Thread(target=race, args=("worker-a",)),
        threading.Thread(target=race, args=("worker-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    epochs = [item for item in found if item is not None]
    assert epochs == [1]
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        owner, epoch, status = conn.execute(
            text("SELECT lease_owner, lease_epoch, status FROM runs WHERE id = :id"),
            {"id": created.run_id},
        ).one()
    engine.dispose()
    assert owner in {"worker-a", "worker-b"}
    assert epoch == 1
    assert status == "leased"

    calls = {"count": 0}

    def write_tool() -> str:
        calls["count"] += 1
        raise ConnectionError("tool network down")

    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

    journal = ToolExecutionJournal(tmp_path / "journal")
    attempt_id = "att_" + "c3" * 16
    first = attempt_tool(journal, attempt_id, "write", {"path": "a.txt"}, write_tool)
    second = attempt_tool(journal, attempt_id, "write", {"path": "a.txt"}, write_tool)
    assert first["run_status"] == "recovery_required"
    assert second["action"] == "uncertain"
    assert second["executed"] is False
    assert calls["count"] == 1
