"""WEB-W2-C02. One tenant cannot read another tenant's project or session."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.main import create_app
from rxycode_server.persistence.migrate import upgrade_head

ORIGIN = "http://127.0.0.1"
SECRET = "local-web-secret-value-32bytes!!"


def _login(client: TestClient) -> str:
    csrf = client.get("/api/v1/auth/csrf")
    assert csrf.status_code == 200
    token = csrf.json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": ORIGIN}
    logged = client.post("/api/v1/auth/local/login", headers=headers)
    assert logged.status_code == 200
    return token


def test_w2_c02_integration(postgres_url: str):
    """User A cannot see user B's project name or session title."""
    upgrade_head(postgres_url)
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
    )
    owner = TestClient(app)
    token = _login(owner)
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
    other = TestClient(app)
    _login(other)
    project = other.get(f"/api/v1/projects/{project_id}")
    session = other.get(f"/api/v1/sessions/{session_id}")
    listing = other.get("/api/v1/projects")
    assert project.status_code == 404
    assert session.status_code == 404
    assert "owner-only" not in project.text
    assert "owner-title" not in session.text
    assert "owner-only" not in listing.text
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        tenant = conn.execute(
            text("SELECT tenant_id FROM projects WHERE id = :id"),
            {"id": project_id},
        ).scalar()
    assert tenant == created.json()["tenant_id"]
