"""WEB-W2-C02. Login returns the database user, and a bad write does not land."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.main import create_app, serve
from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import Organization, Project, User

ORIGIN = "http://127.0.0.1"
SECRET = "local-web-secret-value-32bytes!!"
CLOUD = "https://cloud.example"


def _headers(token: str, origin: str = ORIGIN) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": origin, "X-Local-Secret": SECRET}


def _callback_cookie(app, state: str, oauth_cookie: str) -> str:
    """Read the cloud session Set-Cookie from the OAuth callback response."""
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    query = f"state={state}&code=cloud-code".encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/auth/github/callback",
        "raw_path": b"/api/v1/auth/github/callback",
        "query_string": query,
        "headers": [(b"cookie", f"rxy_oauth={oauth_cookie}".encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 443),
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    assert start["status"] == 200
    chunks = [
        value.decode()
        for key, value in start["headers"]
        if key.lower() == b"set-cookie"
    ]
    return "\n".join(chunks).casefold()


def _csrf(client) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_w2_c02_contract(postgres_url: str):
    """A real login is readable from GET /me, and the legacy app is not the gateway."""
    upgrade_head(postgres_url)
    with pytest.raises(RuntimeError, match="public web gateway"):
        serve(
            mode="local",
            host="0.0.0.0",
            database_url=postgres_url,
            secret=SECRET,
            allowed_origins=[ORIGIN],
        )
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="http://127.0.0.1/api/v1/auth/github/callback",
    )
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/chat" not in paths
    assert "/api/v1/me" in app.openapi()["paths"]
    client = TestClient(app)
    token = _csrf(client)
    first = client.post("/api/v1/auth/local/login", headers=_headers(token))
    assert first.status_code == 200
    old_cookie = client.cookies.get("rxy_session")
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    body = me.json()
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        user = db.get(User, body["user"]["id"])
        org = db.scalars(
            select(Organization).where(Organization.tenant_id == body["organization"]["tenant_id"])
        ).one()
    assert user is not None
    assert body["user"]["kind"] == user.kind == "local"
    assert body["organization"]["tenant_id"] == org.tenant_id
    assert body["membership"]["role"] == "owner"
    user_id = body["user"]["id"]
    token = _csrf(client)
    created = client.post(
        "/api/v1/projects",
        json={"name": "kept", "repo_config": {}},
        headers=_headers(token),
    )
    assert created.status_code == 200
    token = _csrf(client)
    again = client.post("/api/v1/auth/local/login", headers=_headers(token))
    assert again.status_code == 200
    stale = TestClient(app)
    stale.cookies.set("rxy_session", old_cookie)
    denied = stale.get("/api/v1/me")
    assert denied.status_code == 401
    assert denied.json()["code"] == "UNAUTHORIZED"
    again_me = client.get("/api/v1/me")
    assert again_me.json()["user"]["id"] == user_id
    kept = client.get(f"/api/v1/projects/{created.json()['id']}")
    assert kept.status_code == 200
    started = client.get("/api/v1/auth/github/start")
    assert started.status_code == 200
    state = started.json()["state"]
    challenge = started.json()["code_challenge"]
    verifier = app.state.oauth_states[state].verifier
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert challenge == expected
    assert "code_challenge=" + challenge in started.json()["authorization_url"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            sent = request.content.decode()
            assert f"code_verifier={verifier}" in sent
            assert "client_secret=github-secret-not-stored" in sent
            return httpx.Response(200, json={"access_token": "ghs_secret", "token_type": "bearer"})
        assert request.headers["Authorization"] == "Bearer ghs_secret"
        return httpx.Response(200, json={"id": 4242, "login": "octo"})

    app.state.github_transport = httpx.MockTransport(handler)
    stranger = TestClient(app)
    stolen = stranger.get("/api/v1/auth/github/callback", params={"state": state, "code": "abc"})
    assert stolen.status_code == 400
    callback = client.get("/api/v1/auth/github/callback", params={"state": state, "code": "abc"})
    assert callback.status_code == 200
    github_me = client.get("/api/v1/me")
    assert github_me.status_code == 200
    assert github_me.json()["user"]["github_id"] == "4242"
    assert "ghs_secret" not in github_me.text
    with Session(engine) as db:
        stored = db.scalars(select(User).where(User.github_id == "4242")).one()
    assert stored.kind == "github"
    cloud = create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[CLOUD],
    )
    cloud_client = TestClient(cloud)
    cloud_token = _csrf(cloud_client)
    refused = cloud_client.post("/api/v1/auth/local/login", headers=_headers(cloud_token, CLOUD))
    assert refused.status_code == 403
    cloud.state.github_client_id = "iv1.client"
    cloud.state.github_client_secret = "github-secret-not-stored"
    cloud.state.github_redirect_uri = "https://cloud.example/callback"
    def cloud_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(200, json={"access_token": "ghs_other", "token_type": "bearer"})
        return httpx.Response(200, json={"id": 777, "login": "cloud-user"})

    cloud.state.github_transport = httpx.MockTransport(cloud_handler)
    cloud_start = cloud_client.get("/api/v1/auth/github/start")
    cookie = _callback_cookie(
        cloud,
        cloud_start.json()["state"],
        cloud_client.cookies.get("rxy_oauth"),
    )
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie


def test_w2_c02_negative(postgres_url: str):
    """A missing CSRF token or a foreign Origin does not insert a project."""
    upgrade_head(postgres_url)
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
    )
    engine = create_engine(postgres_url)
    client = TestClient(app)
    token = _csrf(client)
    assert client.post("/api/v1/auth/local/login", headers=_headers(token)).status_code == 200
    token = _csrf(client)
    missing = client.post(
        "/api/v1/projects",
        json={"name": "nope", "repo_config": {}},
        headers={"Origin": ORIGIN},
    )
    evil = client.post(
        "/api/v1/projects",
        json={"name": "evil", "repo_config": {}},
        headers=_headers(token, "https://evil.example"),
    )
    leaked = client.post(
        "/api/v1/projects",
        json={"name": "keyed", "repo_config": {"api_key": "sk-live"}},
        headers=_headers(token),
    )
    assert missing.status_code == 403
    assert evil.status_code == 403
    assert leaked.status_code == 400
    with Session(engine) as db:
        count = db.scalar(select(func.count()).select_from(Project))
    assert count == 0
