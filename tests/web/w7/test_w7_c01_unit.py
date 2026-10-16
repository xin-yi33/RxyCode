"""WEB-W7-C01. Contract and negative security checks for auth, tenants, and grants.

Contract: guessing another tenant's ids must yield no data on every resource
surface (project, session, run events, artifacts, devices).
Negative: a forged cloud-side ``full`` permission cannot execute Remote Full
without a locally confirmed grant.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

ORIGIN = "https://cloud.example"
SECRET = "local-web-secret-value-32bytes!!"


def _github(app, client: TestClient, github_id: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(
                200, json={"access_token": f"ghs_{github_id}", "token_type": "bearer"}
            )
        return httpx.Response(200, json={"id": github_id, "login": f"user-{github_id}"})

    app.state.github_transport = httpx.MockTransport(handler)
    started = client.get("/api/v1/auth/github/start")
    assert started.status_code == 200
    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"state": started.json()["state"], "code": f"code-{github_id}"},
    )
    assert callback.status_code == 200
    assert f"ghs_{github_id}" not in callback.text


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": ORIGIN}


def _cloud_app(postgres_url: str):
    from rxycode_server.main import create_app
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(postgres_url)
    return create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="https://cloud.example/callback",
    )


def test_w7_c01_contract(postgres_url: str) -> None:
    """Guessing ids across tenants leaks nothing on any surface."""
    from rxycode_server.devices.gateway import DeviceRecord
    from rxycode_server.persistence.models import Artifact
    from rxycode_server.runs.service import create_run

    app = _cloud_app(postgres_url)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 701)
    headers = _csrf(owner)
    project = owner.post(
        "/api/v1/projects",
        json={"name": "p0-own", "repo_config": {}},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["id"]
    tenant_id = project.json()["tenant_id"]
    session = owner.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "p0-session"},
        headers=headers,
    )
    assert session.status_code == 200
    session_id = session.json()["id"]
    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="run it",
        target_id="cloud:sandbox",
        permission_profile="full",
        request_id="req-" + uuid.uuid4().hex,
    )
    run_id = accepted.run_id
    artifact_id = "art-" + uuid.uuid4().hex[:12]
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(
                Artifact(
                    id=artifact_id,
                    run_id=run_id,
                    object_key=f"runs/{run_id}/out.txt",
                    sha256="0" * 64,
                    size=17,
                    content_type="text/plain",
                )
            )
            db.commit()
    finally:
        engine.dispose()
    device_id = "dev-" + uuid.uuid4().hex[:12]
    app.state.device_registry.devices[device_id] = DeviceRecord(
        tenant_id=tenant_id,
        os_name="windows",
        capabilities=["shell"],
        scope="device",
        token_hash="x" * 64,
        session_id="s",
        last_seen=time.time(),
    )

    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 702)
    forged = attacker.post(
        "/api/v1/projects",
        json={"name": "atk", "repo_config": {}, "tenant_id": tenant_id},
        headers=_csrf(attacker),
    )
    assert forged.status_code == 200
    assert forged.json()["tenant_id"] != tenant_id

    assert attacker.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert attacker.get(f"/api/v1/sessions/{session_id}").status_code == 404
    events = attacker.get(f"/api/v1/runs/{run_id}/events")
    assert events.status_code == 404
    assert "run it" not in events.text
    listed = attacker.get(f"/api/v1/runs/{run_id}/artifacts")
    assert listed.status_code == 403
    assert "p0-artifact-body" not in listed.text
    download = attacker.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}")
    assert download.status_code in (403, 404)
    assert "p0-artifact-body" not in download.text
    invoked = attacker.post(
        f"/api/v1/devices/{device_id}/invocations",
        json={"tool": "bash", "permission": "full", "args": {"command": "whoami"}},
        headers=_csrf(attacker),
    )
    assert invoked.status_code == 404
    devices = attacker.get("/api/v1/devices")
    assert devices.status_code == 200
    assert device_id not in devices.text

    anonymous = TestClient(app, base_url="https://cloud.example")
    assert anonymous.get("/api/v1/me").status_code == 401
    assert anonymous.get(f"/api/v1/projects/{project_id}").status_code == 401
    assert anonymous.get(f"/api/v1/runs/{run_id}/events").status_code == 401
    no_csrf = owner.post(
        "/api/v1/devices/x/invocations",
        json={"tool": "bash", "permission": "full", "args": {}},
    )
    assert no_csrf.status_code == 403


def test_w7_c01_negative(tmp_path: Path) -> None:
    """A cloud mirror forged to ``full`` cannot run Remote Full without a local grant."""
    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        install_grant_store,
    )
    from rxycode_runner.local.supervisor import ProcessSupervisor, bind_supervisor
    from rxycode_runner.transport.tool_rpc import _DEVICE, _run_remote_full
    from rxycode_server.devices.grants import GrantMirror

    work = REPO / "tests" / "web" / "w7" / "_neg_c01"
    work.mkdir(parents=True, exist_ok=True)
    mirror = GrantMirror()
    mirror.request_remote_full(
        device_id="dev-c01-neg",
        session_id="sess-c01",
        run_id="run-c01",
        workspace=str(work),
        capabilities=["shell"],
        expires_at=time.time() + 3600,
    )
    forged = mirror.forge_full("dev-c01-neg")
    assert forged["permission"] == "full"

    store = GrantStore(tmp_path / "grants")
    install_grant_store("dev-c01-neg", store)
    supervisor = ProcessSupervisor()
    bind_supervisor(supervisor)
    token = _DEVICE.set("dev-c01-neg")
    try:
        with pytest.raises(RuntimeError, match="GRANT_REQUIRED"):
            _run_remote_full(
                {
                    "permission": "full",
                    "session_id": "sess-c01",
                    "run_id": "run-c01",
                    "workspace": str(work),
                    "workdir": str(work),
                    "command": "echo pwn > pwn.txt",
                    "timeout": 10,
                },
                tool="bash",
                call_id="call-c01-neg",
                cancel=threading.Event(),
            )
        entries = store.audit_entries()
        assert any(
            item.get("allowed") is False and item.get("reason") == "GRANT_REQUIRED"
            for item in entries
        )
        assert not (work / "pwn.txt").exists()
    finally:
        _DEVICE.reset(token)
        bind_supervisor(None)
        clear_grant_store("dev-c01-neg")
        work.rmdir()
