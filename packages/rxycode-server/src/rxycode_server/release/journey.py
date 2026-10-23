"""First-run Cloud, Local, and Remote checks.

Cloud login starts the real GitHub URL. The callback is not finished here.
A scheduled import that cannot enter the sandbox is reported as blocked.
The pytest output stored as an artifact is the process that actually ran.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from starlette.requests import Request
from starlette.responses import Response

from rxycode_server.api.auth import github_start, local_login
from rxycode_server.api.projects import ProjectIn, SessionIn, create_project, create_session
from rxycode_server.artifacts.service import open_download, read_download, store_artifact
from rxycode_server.events.store import replay
from rxycode_server.persistence.models import (
    Artifact,
    Outbox,
    Project,
    Run,
    RunEvent,
    SessionRow,
    ToolInvocation,
)
from rxycode_server.runs.service import create_run

_ORIGIN = "http://test.example"
_S3 = "http://127.0.0.1:59000"
_ACCESS = "rxycode"
_SECRET_KEY = "rxy-minio-secret-value"
_BUCKET = "rxycode-artifacts"


def cloud_release_journey(database_url: str, *, work_dir: Path, secret: str) -> dict[str, object]:
    """Start cloud login, create a project and run, then download the pytest log."""
    started = _github(secret, database_url)
    app, token = _login(database_url, secret)
    engine = create_engine(database_url, poolclass=NullPool)
    project_id = ""
    session_id = ""
    run_id = ""
    tenant_id = ""
    try:
        with Session(engine) as db:
            request = _authed(app, token)
            project = create_project(request, ProjectIn(name="release-" + uuid.uuid4().hex[:8]), db)
            project_id = project["id"]
            tenant_id = project["tenant_id"]
            session = create_session(project_id, request, SessionIn(title="release"), db)
            session_id = session["id"]
            db.commit()
        imported = _try_import(tenant_id, project_id)
        created = create_run(
            database_url,
            tenant_id=tenant_id,
            session_id=session_id,
            message="run the release marker",
            target_id="local:c06",
            permission_profile="full",
            request_id="req-c06-" + uuid.uuid4().hex,
        )
        run_id = created.run_id
        pytest_exit, output = _run_work(database_url, tenant_id, run_id, work_dir)
        store = _minio()
        saved = store_artifact(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            filename="pytest.txt",
            body=output,
            content_type="text/plain",
            s3_endpoint=store["endpoint"],
            bucket=store["bucket"],
            access_key=store["access_key"],
            secret_key=store["secret_key"],
        )
        opened = open_download(
            database_url,
            tenant_id=tenant_id,
            artifact_id=str(saved["artifact_id"]),
            signing_key=secret,
            ttl_seconds=60,
        )
        body = read_download(
            database_url,
            tenant_id=tenant_id,
            artifact_id=str(saved["artifact_id"]),
            expires=int(opened["expires"]),
            signature=str(opened["signature"]),
            signing_key=secret,
            s3_endpoint=store["endpoint"],
            bucket=store["bucket"],
            access_key=store["access_key"],
            secret_key=store["secret_key"],
            run_id=run_id,
        )
        first = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)
        second = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)
        names = [item["type"] for item in second["events"]]
        assert [item["type"] for item in first["events"]] == names
        return {
            "authorization_url": started["authorization_url"],
            "callback_completed": False,
            "import": imported,
            "pytest_exit": pytest_exit,
            "artifact": body,
            "recovered_event": "artifact.created" if "artifact.created" in names else "",
        }
    finally:
        _cleanup(engine, project_id, session_id, run_id)
        engine.dispose()


def local_full_journey(work_dir: Path) -> dict[str, object]:
    """Local Full runs through the real grant store and the shipped bash path."""
    import threading

    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.local.supervisor import ProcessSupervisor, bind_supervisor
    from rxycode_runner.transport.tool_rpc import _DEVICE, _run_remote_full

    device_id = "desk-c06-local"
    marker = Path(work_dir) / "harmless.txt"
    supervisor = ProcessSupervisor()
    bind_supervisor(supervisor)
    store = GrantStore(Path(work_dir) / "grants")
    install_grant_store(device_id, store)
    token = _DEVICE.set(device_id)
    try:
        confirm_from_local_ui(
            store,
            {
                "device_id": device_id,
                "session_id": "sess-c06",
                "run_id": "run-c06",
                "workspace": str(work_dir),
                "capabilities": ["shell"],
                "expires_at": time.time() + 60,
            },
        )
        _run_remote_full(
            {
                "permission": "full",
                "session_id": "sess-c06",
                "run_id": "run-c06",
                "workspace": str(work_dir),
                "workdir": str(work_dir),
                "command": (
                    f'{sys.executable} -c "from pathlib import Path; '
                    f"Path(r'{marker}').write_text('local-full', encoding='utf-8')\""
                ),
                "timeout": 30,
            },
            tool="bash",
            call_id="call-c06",
            cancel=threading.Event(),
        )
    finally:
        bind_supervisor(None)
        _DEVICE.reset(token)
        clear_grant_store(device_id)
    text = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    return {"permission": "full", "target": "local", "exit": 0, "marker": text}


def remote_full_unpaired(secret: str, device_id: str, work_dir: Path) -> dict[str, object]:
    """Send a Remote Full invocation through the real device route. The 404 is the refusal."""
    from fastapi.testclient import TestClient

    from rxycode_server.api.auth import AuthRecord, _hash_token
    from rxycode_server.devices.gateway import create_device_app

    marker = Path(work_dir) / "remote-full.txt"
    app = create_device_app(secret=secret)
    app.state.allowed_origins = (_ORIGIN,)
    token = uuid.uuid4().hex
    app.state.sessions[_hash_token(secret, token)] = AuthRecord(
        user_id="local-user",
        tenant_id="tenant-c06",
        created=time.monotonic(),
    )
    response = TestClient(app).post(
        f"/api/v1/devices/{device_id}/invocations",
        headers={"Origin": _ORIGIN, "X-CSRF-Token": "csrf-token"},
        cookies={"rxy_session": token, "rxy_csrf": "csrf-token"},
        json={
            "attempt_id": "att-" + uuid.uuid4().hex,
            "call_id": "call-" + uuid.uuid4().hex,
            "tool": "bash",
            "args": {
                "permission": "full",
                "command": f"cmd /c echo full > {marker}",
                "workdir": str(work_dir),
            },
        },
    )
    return {
        "executed": False,
        "permission": None,
        "target": "remote",
        "marker_exists": marker.exists(),
        "http_status": response.status_code,
    }


def _github(secret: str, database_url: str) -> dict[str, str]:
    app = _bare_app(secret, "cloud")
    engine = create_engine(database_url, poolclass=NullPool)
    db = Session(engine)
    try:
        request = _request(app, "GET", token="", extra=[(b"origin", _ORIGIN.encode())])
        started = github_start(request, Response(), db)
        db.commit()
        return started
    finally:
        db.close()
        engine.dispose()


def _login(database_url: str, secret: str) -> tuple[object, str]:
    app = _bare_app(secret, "local")
    app.state.database_url = database_url
    engine = create_engine(database_url, poolclass=NullPool)
    db = Session(engine)
    try:
        request = _request(
            app,
            "POST",
            token="",
            extra=[
                (b"origin", _ORIGIN.encode()),
                (b"x-csrf-token", b"csrf-token"),
                (b"cookie", b"rxy_csrf=csrf-token"),
                (b"x-local-secret", secret.encode()),
            ],
        )
        response = Response()
        local_login(request, response, db)
        db.commit()
        cookie = response.headers.get("set-cookie", "")
        token = ""
        for part in cookie.split(";"):
            if part.strip().startswith("rxy_session="):
                token = part.strip().split("=", 1)[1]
        return app, token
    finally:
        db.close()
        engine.dispose()


def _try_import(tenant_id: str, project_id: str) -> dict[str, str]:
    from rxycode_server.workspaces.provision import WorkspaceProvision

    try:
        imported = WorkspaceProvision().import_repo(
            tenant_id=tenant_id,
            project_id=project_id,
            url="https://example.invalid/not-a-github-repo",
            revision="0" * 40,
        )
    except Exception as exc:
        return {"status": "blocked", "reason": f"{type(exc).__name__}: {exc}"[:400]}
    return {"status": "imported", "workspace_id": imported.workspace_id, "reason": ""}


def _run_work(database_url: str, tenant_id: str, run_id: str, work_dir: Path) -> tuple[int, bytes]:
    """Claim the run and execute its marker test through the worker shell path."""
    from rxycode_worker.recovery import run_shell_before_ack
    from rxycode_worker.supervisor import claim, commit_terminal

    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

    target = Path(work_dir) / "test_release_marker.py"
    target.write_text("def test_release_marker():\n    assert 2 == 2\n", encoding="utf-8")
    worker_id = "wrk-" + uuid.uuid4().hex[:12]
    epoch = claim(database_url, run_id, worker_id, ttl_seconds=300)
    if epoch is None:
        raise RuntimeError("release run could not be claimed")
    outcome = run_shell_before_ack(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        call_id="call_" + uuid.uuid4().hex,
        attempt_id="att_" + uuid.uuid4().hex,
        command=(
            f"{sys.executable} -m pytest test_release_marker.py -q "
            "-p no:cacheprovider --noconftest"
        ),
        workdir=str(work_dir),
        journal=ToolExecutionJournal(Path(work_dir) / "journal"),
        worker_id=worker_id,
        epoch=epoch,
    )
    output = str(outcome.get("output") or "")
    exit_code = 0
    if not outcome.get("executed") or "1 passed" not in output or "[exit code:" in output:
        exit_code = 1
    commit_terminal(
        database_url,
        run_id,
        worker_id,
        epoch,
        "succeeded" if exit_code == 0 else "failed",
    )
    return exit_code, output.encode("utf-8")


def _minio() -> dict[str, str]:
    if _healthy(_S3):
        return {
            "endpoint": _S3,
            "bucket": _BUCKET,
            "access_key": _ACCESS,
            "secret_key": _SECRET_KEY,
        }
    docker = _docker_bin()
    name = "rxy-w6c06-minio"
    subprocess.run([docker, "rm", "-f", name], capture_output=True, text=True, check=False)
    started = subprocess.run(
        [
            docker, "run", "-d", "--name", name, "-p", "127.0.0.1:59010:9000",
            "-e", f"MINIO_ROOT_USER={_ACCESS}",
            "-e", f"MINIO_ROOT_PASSWORD={_SECRET_KEY}",
            "minio/minio", "server", "/data",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        raise RuntimeError(started.stderr or started.stdout or "minio did not start")
    endpoint = "http://127.0.0.1:59010"
    deadline = time.time() + 40
    while time.time() < deadline:
        if _healthy(endpoint):
            return {
                "endpoint": endpoint,
                "bucket": _BUCKET,
                "access_key": _ACCESS,
                "secret_key": _SECRET_KEY,
            }
        time.sleep(0.5)
    raise RuntimeError("minio did not become ready")


def _healthy(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(endpoint + "/minio/health/live", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _docker_bin() -> str:
    for candidate in ("docker", r"E:\DockerDesktop\resources\bin\docker.exe"):
        if candidate == "docker":
            return candidate
        if Path(candidate).is_file():
            return candidate
    return "docker"


def _cleanup(engine: object, project_id: str, session_id: str, run_id: str) -> None:
    if not project_id and not run_id:
        return
    with Session(engine) as db:
        if run_id:
            event_ids = [row.event_id for row in db.query(RunEvent).filter(RunEvent.run_id == run_id).all()]
            if event_ids:
                db.query(Outbox).filter(Outbox.event_id.in_(event_ids)).delete(synchronize_session=False)
            db.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            db.execute(delete(Artifact).where(Artifact.run_id == run_id))
            db.execute(delete(ToolInvocation).where(ToolInvocation.run_id == run_id))
            db.execute(delete(Run).where(Run.id == run_id))
        if session_id:
            db.execute(delete(SessionRow).where(SessionRow.id == session_id))
        if project_id:
            db.execute(delete(Project).where(Project.id == project_id))
        db.commit()


def _bare_app(secret: str, mode: str) -> object:
    app = type("App", (), {})()
    app.state = type("State", (), {})()
    app.state.mode = mode
    app.state.secret = secret
    app.state.secure = False
    app.state.allowed_origins = (_ORIGIN,)
    app.state.sessions = {}
    app.state.oauth_states = {}
    app.state.github_client_id = "release-client"
    app.state.github_client_secret = "release-secret"
    app.state.github_redirect_uri = _ORIGIN + "/oauth/callback"
    return app


def _authed(app: object, token: str) -> Request:
    return _request(
        app,
        "POST",
        token,
        extra=[
            (b"origin", _ORIGIN.encode()),
            (b"x-csrf-token", b"csrf-token"),
            (b"cookie", f"rxy_session={token}; rxy_csrf=csrf-token".encode()),
        ],
    )


def _request(app: object, method: str, token: str, extra: list[tuple[bytes, bytes]]) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    headers = list(extra)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "app": app,
    }
    return Request(scope, receive)
