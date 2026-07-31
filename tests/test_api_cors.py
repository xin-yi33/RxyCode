"""CORS 白名单回归测试。

任意端口的 localhost 曾经被 allow_origin_regex 放行，导致本机任何网页
都能驱动 Agent。这些测试锁死该行为不再回归。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    api_server.configure_api_token("cors-test-token")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_allowed_origin_gets_cors_header(client):
    resp = client.options(
        "/status",
        headers={
            "Origin": "http://127.0.0.1:8765",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8765"


@pytest.mark.parametrize("origin", [
    "http://localhost:3000",
    "http://localhost:9999",
    "http://127.0.0.1:1337",
    "http://evil.example.com",
])
def test_unlisted_origin_is_rejected(client, origin):
    resp = client.options(
        "/status",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


def test_env_override(monkeypatch):
    monkeypatch.setenv("RXYCODE_ALLOWED_ORIGINS", "http://localhost:4321")
    from RxyCode.RxyCode1_1_0 import api_server
    assert api_server._resolve_allowed_origins() == ["http://localhost:4321"]
