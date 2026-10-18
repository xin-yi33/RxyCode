"""WEB-W7-C05. Restart/断电 on the real compose stack loses no durable data.

Given the stack up and migrated, a durable run row plus a journaled event are
written through the REAL spine (``runs.service.create_run`` + ``append_event``)
against the COMPOSE Postgres (published loopback port, per-test credentials).
The DEPLOYED worker (``python -m rxycode_worker.drain`` inside the worker
container — not the test process) claims the run and drives it to a terminal
status. ``docker compose restart postgres api`` then bounces the stateful
services — the named pg volume survives, the api container re-runs its
bootstrap and re-passes health. Afterwards:

- the run row, its ``run.created`` event and the marker event are all read
  back unchanged (no data loss);
- a dead worker's expired lease — planted verbatim via SQL, the same state a
  crashed worker leaves — is honestly re-claimed by a fresh ``worker_id``
  (``supervisor.claim`` bumps ``lease_epoch``) and committed terminal;
- the worker container itself is SIGKILLed and recreated; the revived drain
  claims a third run — the deployed executor survives a worker loss;
- the HTTPS gateway still serves ``/api/v1/auth/csrf`` after the restart.

The drain turn has no provider credentials in the test project, so the
executed run ends ``failed`` — the assertion is the REAL claim + journal +
terminal path through the deployed worker, not a stubbed success.

Skip policy: only a missing docker CLI/engine skips.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]

# The checkout is seeded into the `repo-src` volume through `reposync` — this
# Docker Desktop does not mount Windows bind paths, so the test streams a tar
# over the exec stdin instead of relying on `volumes:` binds.
_REPO_INCLUDE = (
    "__init__.py",
    "__main__.py",
    "main.py",
    "api_server.py",
    "api_server_models.py",
    "api_server_stream.py",
    "common_elements.py",
    "entrypoint.py",
    "pyproject.toml",
    "requirements.txt",
    "appserver",
    "auth",
    "cache",
    "config",
    "core",
    "execution",
    "history",
    "log",
    "lsp",
    "mcp",
    "memory",
    "planning",
    "plugins",
    "protocol",
    "rag",
    "recovery",
    "scheduler",
    "synthesis",
    "tools",
    "utils",
    "validation",
    "packages",
    "apps",
    "infra",
)
_REPO_INCLUDE_FILES = ("frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts",)
_EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", "dist", "build", ".venv"}


def _repo_tar() -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()

    def _keep(info: Any) -> Any:
        if any(part in _EXCLUDE_DIRS for part in Path(info.name).parts):
            return None
        if info.name.endswith(".pyc"):
            return None
        return info

    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel in _REPO_INCLUDE:
            source = REPO / rel
            if source.is_dir():
                tar.add(source, arcname=rel, filter=_keep)
            elif source.is_file():
                tar.add(source, arcname=rel, filter=_keep)
        for rel in _REPO_INCLUDE_FILES:
            source = REPO / rel
            assert source.is_file(), f"missing seeded file {rel}"
            tar.add(source, arcname=rel, filter=_keep)
        marker = tarfile.TarInfo(".rxy-sync-done")
        marker.size = 0
        marker.mtime = int(time.time())
        tar.addfile(marker)
    return buffer.getvalue()


def _seed_repo(project: str, env: dict[str, str]) -> None:
    payload = _repo_tar()
    last = b""
    for _attempt in range(30):
        push = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "-p",
                project,
                "exec",
                "-T",
                "reposync",
                "sh",
                "-c",
                "tar -xf - -C /repo",
            ],
            input=payload,
            capture_output=True,
            check=False,
            env=env,
            timeout=300,
        )
        if push.returncode == 0:
            return
        last = push.stderr
        time.sleep(2)
    raise RuntimeError(f"repo seed failed:\n{last.decode(errors='replace')}")


for _entry in (
    REPO,
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

COMPOSE_FILE = REPO / "infra" / "compose" / "compose.yaml"
STACK_TIMEOUT = 1500.0
SERVICE_MISSING_GRACE = 120.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _stack_env(pg_port: int, https_port: int, http_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "RXYCODE_POSTGRES_PASSWORD": f"pg-{secrets.token_urlsafe(24)}",
            "RXYCODE_MINIO_ROOT_USER": f"minio-{secrets.token_hex(8)}",
            "RXYCODE_MINIO_ROOT_PASSWORD": f"minio-{secrets.token_urlsafe(24)}",
            "RXYCODE_WEB_SECRET": secrets.token_urlsafe(40),
            "RXYCODE_WEB_ORIGINS": f"https://localhost:{https_port}",
            "RXYCODE_PG_PORT": str(pg_port),
            "RXYCODE_HTTPS_PORT": str(https_port),
            "RXYCODE_HTTP_PORT": str(http_port),
            "RXYCODE_GITHUB_CLIENT_ID": "",
            "RXYCODE_GITHUB_CLIENT_SECRET": "",
            "RXYCODE_GITHUB_REDIRECT_URI": "",
            # Short drain cycles so the deployed worker claims quickly; the
            # provider-less turn is bounded by the run timeout.
            "RXYCODE_WORKER_POLL_SECONDS": "1",
            "RXYCODE_WORKER_LEASE_TTL": "30",
            "RXYCODE_WORKER_RUN_TIMEOUT": "60",
            # Give the worker a real configured model pointed at a loopback
            # dead port: the HTTPS-when-credentialed rule exempts loopback,
            # the turn genuinely starts (event/agent_started is journaled),
            # then the provider call fails at the real network boundary —
            # connection refused. No stub LLM, no fabricated success.
            "RXYCODE_LLM_BASE_URL": "http://127.0.0.1:9/v1",
            "RXYCODE_LLM_MODEL": "smoke-none",
            # Non-empty placeholder: the OpenAI client constructs with it and
            # the failure happens at the real HTTP boundary, not at ctor.
            "RXYCODE_API_KEY": f"sk-test-{secrets.token_hex(8)}",
        }
    )
    return env


def _compose(project: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", project, *args]
    done = subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=env,
        timeout=900,
    )
    # text=True would decode with the locale codec (GBK here); docker output
    # is UTF-8, so decode it ourselves — a decode crash leaves stdout=None.
    return subprocess.CompletedProcess(
        command,
        done.returncode,
        (done.stdout or b"").decode("utf-8", errors="replace"),
        (done.stderr or b"").decode("utf-8", errors="replace"),
    )


def _service_states(project: str, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    done = _compose(project, env, "ps", "-a", "--format", "json")
    states: dict[str, dict[str, Any]] = {}
    for line in done.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        row = json.loads(line)
        name = str(row.get("Service") or row.get("Name") or "")
        if name:
            states[name] = row
    return states


_WANTED = {
    "postgres": "healthy",
    "api": "healthy",
    "worker": "healthy",
    "gateway": "healthy",
    "reposync": "exited",
    "migrate": "exited",
    "webbuild": "exited",
}


def _row_ok(row: dict[str, Any], want: str) -> bool:
    state = str(row.get("State") or "").lower()
    health = str(row.get("Health") or "").lower()
    exit_code = str(row.get("ExitCode") if row.get("ExitCode") is not None else "")
    if want == "healthy":
        return health == "healthy"
    if want == "running":
        return state == "running"
    return state == "exited" and exit_code == "0"


def _wait_stack(project: str, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    deadline = time.time() + STACK_TIMEOUT
    missing_deadline = time.time() + SERVICE_MISSING_GRACE
    last: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        last = _service_states(project, env)
        missing = [name for name in _WANTED if name not in last]
        if missing and time.time() > missing_deadline:
            raise RuntimeError(f"services never appeared: {missing}; states={last}")
        if not missing and all(_row_ok(last[name], want) for name, want in _WANTED.items()):
            return last
        time.sleep(3)
    logs = _compose(project, env, "logs", "--no-color", "--tail", "80")
    raise RuntimeError(f"stack did not become healthy; states={last}\n{logs.stdout}\n{logs.stderr}")


def _https_get(url: str, timeout: float = 15.0) -> Any:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    return urllib.request.urlopen(request, context=context, timeout=timeout)


def _seed_tenant(database_url: str, tenant_id: str, session_id: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import (
        Organization,
        Project,
        SessionRow,
        User,
    )

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            # The same tenant is re-seeded for extra sessions later in the
            # test — insert the fixed tenant rows only when absent.
            if db.get(User, f"user-{tenant_id}") is None:
                db.add(User(id=f"user-{tenant_id}", github_id=None, kind="local"))
            if db.get(Organization, f"org-{tenant_id}") is None:
                db.add(Organization(id=f"org-{tenant_id}", tenant_id=tenant_id))
            if db.get(Project, f"prj-{tenant_id}") is None:
                db.add(
                    Project(
                        id=f"prj-{tenant_id}",
                        tenant_id=tenant_id,
                        name="c05-restart",
                        repo_config={},
                    )
                )
            db.add(
                SessionRow(
                    id=session_id,
                    tenant_id=tenant_id,
                    project_id=f"prj-{tenant_id}",
                    title="c05-restart",
                )
            )
            db.commit()
    finally:
        engine.dispose()


@pytest.mark.timeout(1800)
def test_w7_c05_integration() -> None:
    """Restart loses nothing; a stale lease is re-claimed by a fresh worker."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required for the real compose restart proof")
    engine = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if engine.returncode != 0:
        pytest.skip("docker engine is not reachable")

    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.events.store import append_event, replay
    from rxycode_server.runs.service import create_run
    from rxycode_worker.supervisor import claim, commit_terminal

    project = f"rxyw7c05i-{uuid.uuid4().hex[:8]}"
    pg_port = _free_port()
    https_port = _free_port()
    http_port = _free_port()
    env = _stack_env(pg_port, https_port, http_port)
    database_url = (
        "postgresql+psycopg://rxycode:"
        f"{env['RXYCODE_POSTGRES_PASSWORD']}@127.0.0.1:{pg_port}/rxycode"
    )
    https_base = f"https://localhost:{https_port}"

    try:
        # `up` sits inside try/finally: a failed or timed-out start still
        # tears the partial project down.
        up = _compose(project, env, "up", "-d", "--remove-orphans")
        assert up.returncode == 0, f"compose up failed:\n{up.stdout}\n{up.stderr}"
        _seed_repo(project, env)
        states = _wait_stack(project, env)
        assert states["migrate"].get("ExitCode") == 0, states["migrate"]
        assert str(states["api"].get("Health")).lower() == "healthy"

        # -- Seed a durable run + marker event through the real spine --------
        tenant_id = f"tenant-c05-{uuid.uuid4().hex[:8]}"
        session_id = uuid.uuid4().hex
        _seed_tenant(database_url, tenant_id, session_id)
        accepted = create_run(
            database_url,
            tenant_id=tenant_id,
            session_id=session_id,
            message="restart-proof durable run",
            target_id="local:c05",
            permission_profile="full_auto",
            request_id=f"req-c05-{uuid.uuid4().hex[:12]}",
        )
        run_id = accepted.run_id
        marker_seq = append_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="deploy.marker",
            payload={"phase": "pre-restart", "card": "WEB-W7-C05"},
        )

        # -- The DEPLOYED worker drains the queue: the run leaves `pending`,
        # its worker.lease event lands, and the turn reaches a terminal
        # status. No provider creds in the project => expected terminal is
        # `failed`; `succeeded` is accepted too (a configured provider is a
        # legitimate outcome — the assertion is the real executed path).
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            deadline = time.time() + 90
            claimed = None
            while time.time() < deadline:
                with engine.connect() as conn:
                    claimed = conn.execute(
                        text(
                            "SELECT status, lease_owner, lease_epoch FROM runs WHERE id = :run_id"
                        ),
                        {"run_id": run_id},
                    ).one()
                if str(claimed.status) != "pending" and claimed.lease_owner:
                    break
                time.sleep(2)
            else:
                raise AssertionError("deployed drain never claimed the queued run")
            drain_worker = str(claimed.lease_owner)
            terminal = ""
            deadline = time.time() + 150
            while time.time() < deadline:
                with engine.connect() as conn:
                    terminal = str(
                        conn.execute(
                            text("SELECT status FROM runs WHERE id = :run_id"),
                            {"run_id": run_id},
                        ).scalar()
                    )
                if terminal in {"succeeded", "failed"}:
                    break
                time.sleep(3)
            assert terminal in {"succeeded", "failed"}, (
                f"drained run never reached terminal, still {terminal}"
            )
            events = list(
                replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)["events"]
            )
            kinds = [event["type"] for event in events]
            assert "run.created" in kinds
            # The drain's own durable markers prove the real path ran inside
            # the container: the lease event plus the terminal bookkeeping.
            assert "worker.lease" in kinds
            assert "usage.updated" in kinds
            # And the turn machinery really ran: AgentRuntime.spawn ->
            # AgentTask._journal writes event/agent_started through the
            # RunJournal bound by remember_web_run — a row only a real
            # executed turn produces, not a stubbed terminal.
            assert "event/agent_started" in kinds
        finally:
            engine.dispose()

        # -- 断电: bounce the stateful + api services -----------------------
        restart = _compose(project, env, "restart", "postgres", "api")
        assert restart.returncode == 0, restart.stderr
        states = _wait_stack(project, env)
        assert str(states["postgres"].get("Health")).lower() == "healthy"
        assert str(states["api"].get("Health")).lower() == "healthy"

        # -- No data loss: run row + marker event read back identically -----
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status, lease_owner, lease_epoch FROM runs WHERE id = :run_id"),
                    {"run_id": run_id},
                ).one()
                assert str(row.status) == terminal
                assert str(row.lease_owner) == drain_worker
        finally:
            engine.dispose()
        events = list(
            replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)["events"]
        )
        kinds = [event["type"] for event in events]
        assert "run.created" in kinds
        marker = next(e for e in events if e["type"] == "deploy.marker")
        assert int(marker["seq"]) == int(marker_seq)
        assert marker["payload"]["phase"] == "pre-restart"

        # -- Stale-lease reclaim, deterministic: SIGKILL the worker container
        # (its in-memory lease renewals die with it), then plant the exact
        # row a crashed worker leaves — an expired lease owned by a dead
        # worker_id — and a fresh worker claims + commits.
        killed = _compose(project, env, "kill", "worker")
        assert killed.returncode == 0, killed.stderr
        session2 = uuid.uuid4().hex
        _seed_tenant(database_url, tenant_id, session2)
        accepted2 = create_run(
            database_url,
            tenant_id=tenant_id,
            session_id=session2,
            message="stale lease reclaim run",
            target_id="local:c05-b",
            permission_profile="full_auto",
            request_id=f"req-c05b-{uuid.uuid4().hex[:12]}",
        )
        run2 = accepted2.run_id
        dead_worker = f"dead-worker-{uuid.uuid4().hex[:6]}"
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE runs SET status = 'leased',"
                        " lease_owner = :owner, lease_epoch = 1,"
                        " lease_until = :expired WHERE id = :run_id"
                    ),
                    {
                        "owner": dead_worker,
                        "expired": datetime.now(timezone.utc) - timedelta(seconds=5),
                        "run_id": run2,
                    },
                )
        finally:
            engine.dispose()
        worker_b = f"worker-b-{uuid.uuid4().hex[:6]}"
        epoch_b = claim(database_url, run2, worker_b, ttl_seconds=600)
        assert epoch_b == 2, "expired lease must be re-claimable at epoch+1"
        commit_terminal(database_url, run2, worker_b, epoch_b, "succeeded")
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status, lease_owner, lease_epoch FROM runs WHERE id = :run_id"),
                    {"run_id": run2},
                ).one()
                assert str(row.status) == "succeeded"
                assert str(row.lease_owner) == worker_b
                assert int(row.lease_epoch) == 2
        finally:
            engine.dispose()

        # -- Worker restart recovery: recreate the killed worker; the revived
        # drain claims a third queued run on its own.
        recreated = _compose(project, env, "up", "-d", "worker")
        assert recreated.returncode == 0, recreated.stderr
        # A recreated container pays the pip bootstrap again — allow the same
        # window the service start_period grants.
        deadline = time.time() + 660
        healthy = False
        while time.time() < deadline:
            row = _service_states(project, env).get("worker") or {}
            if str(row.get("Health") or "").lower() == "healthy":
                healthy = True
                break
            time.sleep(5)
        assert healthy, "worker container never came back healthy"
        session3 = uuid.uuid4().hex
        _seed_tenant(database_url, tenant_id, session3)
        accepted3 = create_run(
            database_url,
            tenant_id=tenant_id,
            session_id=session3,
            message="post-restart drain run",
            target_id="local:c05-c",
            permission_profile="full_auto",
            request_id=f"req-c05c-{uuid.uuid4().hex[:12]}",
        )
        run3 = accepted3.run_id
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            deadline = time.time() + 90
            owner3 = ""
            while time.time() < deadline:
                with engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT status, lease_owner FROM runs WHERE id = :run_id"),
                        {"run_id": run3},
                    ).one()
                owner3 = str(row.lease_owner or "")
                if str(row.status) != "pending" and owner3:
                    break
                time.sleep(2)
            assert owner3 and owner3 != worker_b, (
                "revived drain worker never claimed the post-restart run"
            )
        finally:
            engine.dispose()

        # -- The gateway still serves the API after the bounce --------------
        csrf = _https_get(f"{https_base}/api/v1/auth/csrf")
        assert csrf.status == 200
        assert json.loads(csrf.read().decode("utf-8"))["csrf_token"]
    finally:
        _compose(project, env, "down", "-v", "--remove-orphans")
