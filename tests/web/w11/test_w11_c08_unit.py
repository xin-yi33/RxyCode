"""WEB-W11-C08. Web capabilities + stable surface prompt layer.

Contract (UI-2026-10-22 §08 API-WEB-CAP, FR-WEB-02): ``GET /me`` reports what
this deployment's web surface can do; model rows carry ``input_capabilities``;
the Web prompt appendix is appended once from the trusted RunContext.surface —
never inferred from user text — and stays a single stable block.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-protocol" / "src",
    REPO,
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


def test_w11_c08_contract(postgres_url: str, tmp_path: Path) -> None:
    """GET /me carries web_capabilities; the flag follows the real store."""
    from rxycode_server.attachments.store import BlobConfig

    app = _cloud_app(postgres_url)
    app.state.attachment_blobs = BlobConfig("fs", root=str(tmp_path))
    client = TestClient(app, base_url="https://cloud.example")
    _github(app, client, 1201)

    me = client.get("/api/v1/me")
    assert me.status_code == 200
    caps = me.json()["web_capabilities"]
    assert caps["surface"] == "web"
    assert caps["attachments"] is True
    assert caps["attachment_max_bytes"] > 0
    assert caps["attachment_max_per_run"] > 0
    kinds = caps["preview"]["kinds"]
    assert kinds["frontend_static"] is True
    assert kinds["image"] is True
    # Honest absence: no converter provisioned → reported false, not omitted.
    assert kinds["pdf"] is False
    assert kinds["office"] is False

    # Without a blob config the surface reports attachments honestly off.
    app.state.attachment_blobs = None
    me2 = client.get("/api/v1/me").json()
    assert me2["web_capabilities"]["attachments"] is False


def test_w11_c08_negative() -> None:
    """RunContext: identity is server-set, secrets refused, surface not claimed."""
    from rxycode_protocol.run_context import RunContext

    base = {
        "tenant_id": "t1",
        "actor_id": "u1",
        "project_id": "p1",
        "session_id": "s1",
        "target_id": "cloud:sandbox",
        "permission_profile": "default",
        "deadline_at": "2026-10-22T00:00:00+00:00",
        "trace_id": "trace-1",
    }
    context = RunContext.from_authenticated(
        base,
        claimed={"tenant_id": "evil", "surface": "web", "run_id": "spoofed"},
    )
    assert context.tenant_id == "t1"
    assert context.surface == ""  # never taken from the client body
    assert context.run_id != "spoofed"

    for secret_key in ("api_key", "device_token", "authorization", "token"):
        payload = dict(base)
        payload[secret_key] = "leak"
        try:
            RunContext.from_authenticated(payload)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"{secret_key} was not refused")

    # Server-set surface survives serialization round-trip.
    web = RunContext(**{**base, "run_id": uuid.uuid4().hex, "surface": "web"})
    assert RunContext(**web.to_dict()).surface == "web"


def test_w11_c08_prompt_appendix() -> None:
    """FR-WEB-02: one stable appendix, only when surface == 'web'."""
    from rxycode_protocol.run_context import (
        RunContext,
        bind_run_context,
        reset_run_context,
    )

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.prompts.web_surface import WEB_SURFACE_APPENDIX

    agent = AgentV2.__new__(AgentV2)
    agent._subagent_system_prompt = None
    agent._prompt_variant = lambda: "default"  # noqa: SLF001 — bare instance

    plain = agent._active_system_prompt()  # noqa: SLF001
    assert WEB_SURFACE_APPENDIX.strip() not in plain

    context = RunContext(
        tenant_id="t",
        actor_id="u",
        project_id="p",
        session_id="s",
        run_id="r",
        target_id="cloud:sandbox",
        permission_profile="default",
        deadline_at="2026-10-22T00:00:00+00:00",
        trace_id="tr",
        surface="web",
    )
    token = bind_run_context(context)
    try:
        webbed = agent._active_system_prompt()  # noqa: SLF001
    finally:
        reset_run_context(token)
    assert webbed.startswith(plain)
    assert webbed.count(WEB_SURFACE_APPENDIX.strip()[:80]) == 1
    assert webbed == plain + WEB_SURFACE_APPENDIX

    # A non-web surface never gets the appendix.
    other = RunContext(
        **{**context.to_dict(), "surface": "opentui"},
    )
    token = bind_run_context(other)
    try:
        still = agent._active_system_prompt()  # noqa: SLF001
    finally:
        reset_run_context(token)
    assert still == plain
