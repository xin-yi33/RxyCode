"""WEB-W7-C01 threat model. Attack cases the shipped boundaries must refuse.

Each test names the attack in plain words, runs it against the real code path,
and asserts refusal (or redaction) plus the absence of any leaked data. When a
protection is verified elsewhere this file still exercises the attack so the
threat table has an executable row.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

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


def _owner_with_session(postgres_url: str):
    app = _cloud_app(postgres_url)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 801)
    headers = _csrf(owner)
    project = owner.post(
        "/api/v1/projects",
        json={"name": "tm-own", "repo_config": {}},
        headers=headers,
    )
    project_id = project.json()["id"]
    session = owner.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "tm-session"},
        headers=headers,
    )
    return app, owner, headers, project_id, session.json()["id"], project.json()["tenant_id"]


def test_threat_cross_tenant(postgres_url: str) -> None:
    """ATTACK: tenant B guesses tenant A's workspace, run approvals and preview ids."""
    from rxycode_server.runs.service import create_run

    app, _owner, _h, project_id, session_id, tenant_id = _owner_with_session(postgres_url)
    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 802)

    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="tm run",
        target_id="cloud:sandbox",
        permission_profile="full",
        request_id="req-tm-1",
    )
    tree = attacker.get(f"/api/v1/workspaces/{project_id}/tree")
    assert tree.status_code == 404
    approvals = attacker.get(f"/api/v1/runs/{accepted.run_id}/approvals")
    assert approvals.status_code == 404
    preview = attacker.get("/api/v1/previews/sbx-1/8080")
    assert preview.status_code == 403
    assert "tm-own" not in tree.text + approvals.text + preview.text


def test_threat_tampered_session(postgres_url: str) -> None:
    """ATTACK: forged, expired and foreign session cookies must not authenticate."""
    app, _owner, _h, project_id, _sid, _tenant = _owner_with_session(postgres_url)
    forged = TestClient(app, base_url="https://cloud.example")
    forged.cookies.set("rxy_session", "forged-token-value")
    assert forged.get("/api/v1/me").status_code == 401
    assert forged.get(f"/api/v1/projects/{project_id}").status_code == 401

    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 803)
    # CSRF write protection also binds Origin: a foreign Origin must 403.
    csrf = attacker.get("/api/v1/auth/csrf").json()["csrf_token"]
    refused = attacker.post(
        "/api/v1/projects",
        json={"name": "evil", "repo_config": {}},
        headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
    )
    assert refused.status_code == 403

    # An expired session cookie must not authenticate: age the durable row
    # past its expiry (WEB-W9-B1: sessions live in auth_sessions now).
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import Session

    from rxycode_server.api.auth import _hash_token
    from rxycode_server.persistence.models import AuthSession

    raw = attacker.cookies.get("rxy_session")
    digest = _hash_token(app.state.secret, raw)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == digest)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        db.commit()
    engine.dispose()
    assert attacker.get("/api/v1/me").status_code == 401


def test_threat_ws_origin(postgres_url: str) -> None:
    """ATTACK: a foreign-Origin browser must not open the terminal WebSocket."""
    app, _owner, _h, _pid, _sid, _tenant = _owner_with_session(postgres_url)
    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 804)
    import starlette.websockets

    with pytest.raises(starlette.websockets.WebSocketDisconnect) as foreign:
        with attacker.websocket_connect(
            "/api/v1/terminals/t-1/ws",
            headers={"Origin": "https://evil.example"},
        ):
            pass
    assert foreign.value.code == 1008
    assert foreign.value.reason == "ORIGIN_FORBIDDEN"
    # Allowed Origin proceeds past the Origin gate (fails ownership instead).
    with pytest.raises(starlette.websockets.WebSocketDisconnect) as owned:
        with attacker.websocket_connect(
            "/api/v1/terminals/t-1/ws",
            headers={"Origin": ORIGIN},
        ):
            pass
    assert owned.value.code == 1008
    assert owned.value.reason != "ORIGIN_FORBIDDEN"

    # Cloud mode must enforce Origin even with an empty allowlist.
    from rxycode_server.main import create_app
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(postgres_url)
    empty_app = create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="https://cloud.example/callback",
    )
    empty_client = TestClient(empty_app, base_url="https://cloud.example")
    _github(empty_app, empty_client, 805)
    with pytest.raises(starlette.websockets.WebSocketDisconnect) as empty:
        with empty_client.websocket_connect(
            "/api/v1/terminals/t-1/ws",
            headers={"Origin": "https://evil.example"},
        ):
            pass
    assert empty.value.code == 1008
    assert empty.value.reason == "ORIGIN_FORBIDDEN"


def test_threat_prompt_injection_grant(tmp_path: Path) -> None:
    """ATTACK: injected call replays a real grant id with changed scope/run/capability."""
    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.local.supervisor import ProcessSupervisor, bind_supervisor
    from rxycode_runner.transport.tool_rpc import _DEVICE, _run_remote_full

    work = REPO / "tests" / "web" / "security" / "_inj_c01"
    work.mkdir(parents=True, exist_ok=True)
    store = GrantStore(tmp_path / "grants")
    install_grant_store("dev-tm", store)
    supervisor = ProcessSupervisor()
    bind_supervisor(supervisor)
    confirm_from_local_ui(
        store,
        {
            "device_id": "dev-tm",
            "session_id": "sess-real",
            "run_id": "run-real",
            "workspace": str(work),
            "capabilities": ["shell"],
            "expires_at": time.time() + 3600,
        },
    )
    token = _DEVICE.set("dev-tm")
    base = {
        "permission": "full",
        "session_id": "sess-real",
        "run_id": "run-real",
        "workspace": str(work),
        "workdir": str(work),
        "command": "echo x",
        "timeout": 5,
    }
    try:
        for field, value, reason in (
            ("run_id", "run-injected", "RUN_MISMATCH"),
            ("session_id", "sess-injected", "SESSION_MISMATCH"),
        ):
            call = dict(base, **{field: value})
            with pytest.raises(RuntimeError, match=reason):
                _run_remote_full(
                    call,
                    tool="bash",
                    call_id="call-inj",
                    cancel=threading.Event(),
                )
        click_call = dict(base, capability_override=True)
        with pytest.raises(RuntimeError, match="CAPABILITY_MISMATCH"):
            _run_remote_full(
                click_call,
                tool="click",
                call_id="call-inj-click",
                cancel=threading.Event(),
            )
        escape = dict(base, workspace=str(REPO), workdir=str(REPO))
        with pytest.raises(RuntimeError, match="WORKSPACE_MISMATCH"):
            _run_remote_full(
                escape,
                tool="bash",
                call_id="call-inj-ws",
                cancel=threading.Event(),
            )
        reasons = [str(item.get("reason")) for item in store.audit_entries()]
        for expected in (
            "RUN_MISMATCH",
            "SESSION_MISMATCH",
            "CAPABILITY_MISMATCH",
            "WORKSPACE_MISMATCH",
        ):
            assert expected in reasons
        assert not any(item.get("allowed") is True for item in store.audit_entries())
    finally:
        _DEVICE.reset(token)
        bind_supervisor(None)
        clear_grant_store("dev-tm")
        work.rmdir()


def test_threat_secret_redaction(tmp_path: Path) -> None:
    """ATTACK: tool args and results carrying keys must not land in the audit log."""
    from RxyCode.RxyCode1_1_0.core.safety.audit import AuditLogger
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    logger.log(
        "bash",
        RiskLevel.WRITE,
        {
            "command": "curl https://api.example",
            "api_key": "sk-proj-a1b2c3d4e5f6a7b8",
            "headers": {"Authorization": "Bearer ghp_a1b2c3d4e5f6a7b8c9d0"},
        },
        "auto-approved",
        "token=zzz9yyy8xxx7 saved ok",
        outcome="succeeded",
        executed=True,
    )
    text = path.read_text(encoding="utf-8")
    for leaked in (
        "sk-proj-a1b2c3d4e5f6a7b8",
        "ghp_a1b2c3d4e5f6a7b8c9d0",
        "zzz9yyy8xxx7",
    ):
        assert leaked not in text
    record = json.loads(text.strip().splitlines()[0])
    assert record["args"]["api_key"] == "***"
    assert record["args"]["headers"]["Authorization"] == "***"


def test_threat_ssrf() -> None:
    """ATTACK: fetch tool must refuse private hosts, link-local and credentialed URLs."""
    from RxyCode.RxyCode1_1_0.utils.safe_http import UnsafeUrlError, validate_public_url

    for url in (
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/loopback",
        "http://user:pass@example.com/",
        "file:///C:/Windows/win.ini",
        "http://localhost/internal",
    ):
        with pytest.raises(UnsafeUrlError):
            validate_public_url(url)


def test_threat_sandbox_fail_closed() -> None:
    """ATTACK: a workdir outside workspace_root must fail, never fall back to host."""
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    marker = Path(r"C:\Windows\Temp\rxy_w7_sandbox.txt")
    marker.unlink(missing_ok=True)
    result = bash_tool.invoke(
        {
            "command": 'cmd /c "echo x > C:\\Windows\\Temp\\rxy_w7_sandbox.txt"',
            "workdir": r"C:\Windows\Temp",
            "timeout": 10,
        }
    )
    text = str(result)
    assert "workspace_root" in text or "outside" in text or "escapes" in text, text
    assert not marker.exists()
