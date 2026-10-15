"""WEB-W2-C02. One tenant cannot read another tenant's project or session."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.main import create_app
from rxycode_server.persistence.migrate import upgrade_head

ORIGIN = "https://cloud.example"
SECRET = "local-web-secret-value-32bytes!!"


def _github(app, client: TestClient, github_id: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(200, json={"access_token": f"ghs_{github_id}", "token_type": "bearer"})
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


def test_w2_c02_integration(postgres_url: str):
    """User A cannot see user B's project name or session title."""
    upgrade_head(postgres_url)
    app = create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="https://cloud.example/callback",
    )
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 101)
    csrf = owner.get("/api/v1/auth/csrf")
    token = csrf.json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": ORIGIN}
    created = owner.post(
        "/api/v1/projects",
        json={"name": "owner-only", "repo_config": {"remote": "a"}, "tenant_id": "attacker"},
        headers=headers,
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    assert created.json()["tenant_id"] != "attacker"
    opened = owner.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "owner-title"},
        headers=headers,
    )
    assert opened.status_code == 200
    session_id = opened.json()["id"]
    listed = owner.get(f"/api/v1/projects/{project_id}/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["title"] == "owner-title"
    other = TestClient(app, base_url="https://cloud.example")
    _github(app, other, 202)
    project = other.get(f"/api/v1/projects/{project_id}")
    session = other.get(f"/api/v1/sessions/{session_id}")
    sessions = other.get(f"/api/v1/projects/{project_id}/sessions")
    listing = other.get("/api/v1/projects")
    assert project.status_code == 404
    assert session.status_code == 404
    assert sessions.status_code == 404
    assert "owner-only" not in project.text
    assert "owner-title" not in session.text
    assert "owner-title" not in sessions.text
    assert "owner-only" not in listing.text
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        tenant = conn.execute(
            text("SELECT tenant_id FROM projects WHERE id = :id"),
            {"id": project_id},
        ).scalar()
    assert tenant == created.json()["tenant_id"]
