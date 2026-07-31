"""Behavioral security and model-onboarding contracts for the local API."""

import inspect
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _client(api_server, *, token: str | None = None, host: str = "127.0.0.1"):
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return TestClient(
        api_server.app,
        client=(host, 50000),
        headers=headers,
    )


def test_api_server_defaults_to_ipv4_loopback():
    from RxyCode.RxyCode1_1_0 import api_server

    assert inspect.signature(api_server.run_api_server).parameters["host"].default == "127.0.0.1"


def test_each_server_start_rotates_the_bearer_token(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    import uvicorn

    monkeypatch.delenv("RXYCODE_ALLOW_REMOTE_API", raising=False)
    monkeypatch.delenv("RXYCODE_API_TOKEN", raising=False)
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)
    api_server.run_api_server()
    first = api_server.get_api_token()
    api_server.run_api_server()
    second = api_server.get_api_token()

    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32


def test_local_reads_and_mutations_require_bearer(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    token = api_server.configure_api_token("local-test-token")
    with _client(api_server) as client:
        for path in ("/status", "/models", "/models/presets"):
            missing = client.get(path)
            assert missing.status_code == 401
            assert missing.headers["www-authenticate"] == "Bearer"
        missing = client.post("/command", json={"command": "/exit"})
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

    with _client(api_server, token="wrong-token") as client:
        assert client.get("/status").status_code == 401
        assert client.get("/models").status_code == 401
        assert client.post("/command", json={"command": "/exit"}).status_code == 401

    with _client(api_server, token=token) as client:
        assert client.get("/status").status_code == 200
        assert client.get("/models").status_code == 200
        response = client.post("/command", json={"command": "/exit"})
        assert response.status_code == 200
        assert response.json()["action"] == "exit"


def test_cors_preflight_remains_public(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    api_server.configure_api_token("preflight-test-token")
    with _client(api_server) as client:
        response = client.options(
            "/status",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize(
    "path",
    [
        "/approve",
        "/log",
        "/chat",
        "/chat/stream",
        "/command",
        "/cancel",
        "/models/onboard",
        "/models/discover",
    ],
)
def test_every_non_read_only_route_rejects_a_missing_token(monkeypatch, path):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    api_server.configure_api_token("required-for-every-post")
    with _client(api_server) as client:
        assert client.post(path, json={}).status_code == 401


def test_remote_clients_are_rejected_even_with_valid_token(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    token = api_server.configure_api_access(
        allow_remote=False, token="remote-test-token"
    )
    with _client(api_server, token=token, host="203.0.113.9") as client:
        assert client.get("/status").status_code == 403
        assert client.post("/command", json={"command": "/exit"}).status_code == 403


def test_remote_bind_fails_closed_without_opt_in_and_strong_token(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    import uvicorn

    run = MagicMock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.delenv("RXYCODE_ALLOW_REMOTE_API", raising=False)
    monkeypatch.delenv("RXYCODE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="RXYCODE_ALLOW_REMOTE_API"):
        api_server.run_api_server(host="0.0.0.0")
    run.assert_not_called()

    monkeypatch.setenv("RXYCODE_ALLOW_REMOTE_API", "1")
    with pytest.raises(RuntimeError, match="high-entropy"):
        api_server.run_api_server(host="0.0.0.0", token="short-token")
    with pytest.raises(RuntimeError, match="high-entropy"):
        api_server.run_api_server(
            host="0.0.0.0",
            token="replace-with-a-random-token-at-least-32-characters",
        )
    strong_token = "remote-test-" + "A7f9xQ2mK8vP4sN6dR3wY5zC"
    with pytest.raises(RuntimeError, match="TLS_CERTFILE"):
        api_server.run_api_server(host="0.0.0.0", token=strong_token)
    run.assert_not_called()


def test_explicit_remote_opt_in_requires_tls_and_bearer_for_all_requests(
    monkeypatch, tmp_path
):
    from RxyCode.RxyCode1_1_0 import api_server
    import uvicorn

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    run = MagicMock()
    monkeypatch.setattr(uvicorn, "run", run)
    token = "remote-test-" + "A7f9xQ2mK8vP4sN6dR3wY5zC"
    monkeypatch.setenv("RXYCODE_ALLOW_REMOTE_API", "1")
    monkeypatch.setenv("RXYCODE_API_TOKEN", token)
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("test certificate", encoding="utf-8")
    key.write_text("test key", encoding="utf-8")

    try:
        api_server.run_api_server(
            host="0.0.0.0", ssl_certfile=cert, ssl_keyfile=key
        )
        run.assert_called_once_with(
            api_server.app,
            host="0.0.0.0",
            port=8765,
            log_level="warning",
            ssl_certfile=str(cert.resolve()),
            ssl_keyfile=str(key.resolve()),
        )
        with _client(api_server, host="203.0.113.9") as client:
            assert client.get("/status").status_code == 401
            assert client.get("/models").status_code == 401
            assert client.post("/command", json={"command": "/exit"}).status_code == 401
        with _client(api_server, host="203.0.113.9", token=token) as client:
            assert client.get("/status").status_code == 200
            assert client.get("/models").status_code == 200
            assert client.post("/command", json={"command": "/exit"}).status_code == 200
    finally:
        api_server.configure_api_access(allow_remote=False)


def test_docker_contract_keeps_plaintext_api_on_shared_loopback_only():
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "run_api_server(host='127.0.0.1'" in dockerfile
    assert "uvicorn.run(app, host='0.0.0.0'" not in dockerfile
    assert '"8765:8765"' not in compose
    assert "RXYCODE_ALLOW_REMOTE_API=1" not in compose
    assert compose.count("RXYCODE_API_TOKEN=${RXYCODE_API_TOKEN:?") == 2
    assert 'network_mode: "service:api"' in compose
    assert "RXYCODE_API_URL=http://127.0.0.1:8765" in compose


def test_frontend_log_redacts_credentials(monkeypatch, caplog):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    token = api_server.configure_api_token("server-bearer-never-log")
    caplog.set_level(logging.INFO, logger="rxycode")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/log",
            json={
                "level": "INFO",
                "message": "failed with " + "Bearer " + "upstream-token-value and sk-sensitive123",
                "context": {
                    "api_key": "sk-context-secret",
                    "nested": {"access_token": "nested-secret", "ok": "visible"},
                },
            },
        )

    assert response.status_code == 200
    assert "server-bearer-never-log" not in caplog.text
    assert "upstream-token-value" not in caplog.text
    assert "sk-sensitive123" not in caplog.text
    assert "sk-context-secret" not in caplog.text
    assert "nested-secret" not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "visible" in caplog.text


def test_failed_model_preflight_never_persists(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(model_manager, "list_models", lambda: {})
    probe = MagicMock(
        return_value={"success": False, "error": "provider rejected opaqueCredential987"}
    )
    add = MagicMock()
    activate = MagicMock()
    remove = MagicMock()
    monkeypatch.setattr(model_manager, "probe_model_connection", probe)
    monkeypatch.setattr(model_manager, "add_model", add)
    monkeypatch.setattr(model_manager, "set_active_model", activate)
    monkeypatch.setattr(model_manager, "remove_model", remove)
    token = api_server.configure_api_token("onboard-failure-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/onboard",
            json={
                "provider_model_id": "provider/model-v2",
                "nickname": "daily-coder",
                "api_key": "opaqueCredential987",
                "base_url": "https://provider.example/v1/",
            },
        )

    assert response.status_code == 400
    assert "opaqueCredential987" not in response.text
    probe.assert_called_once_with(
        api_key="opaqueCredential987",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )
    add.assert_not_called()
    activate.assert_not_called()
    remove.assert_not_called()


def test_successful_onboarding_preserves_nickname_provider_mapping(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(model_manager, "list_models", lambda: {})
    probe = MagicMock(return_value={"success": True, "elapsed": 0.12})
    add = MagicMock(return_value={})
    activate = MagicMock(return_value=True)
    monkeypatch.setattr(model_manager, "probe_model_connection", probe)
    monkeypatch.setattr(model_manager, "add_model", add)
    monkeypatch.setattr(model_manager, "set_active_model", activate)
    token = api_server.configure_api_token("onboard-success-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/onboard",
            json={
                "provider_model_id": "provider/model-v2",
                "nickname": "daily-coder",
                "api_key": "sk-mapping-secret",
                "base_url": "https://provider.example/v1",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["model"]["id"] == "daily-coder"
    assert payload["model"]["nickname"] == "daily-coder"
    assert payload["model"]["provider_model_id"] == "provider/model-v2"
    assert "sk-mapping-secret" not in response.text
    probe.assert_called_once_with(
        api_key="sk-mapping-secret",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )
    add.assert_called_once_with(
        "daily-coder",
        "sk-mapping-secret",
        "https://provider.example/v1",
        model_name="provider/model-v2",
    )
    activate.assert_called_once_with("daily-coder")


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://provider.example/v1",
        "httpjunk://provider.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?token=value",
        "https://provider.example/v1#fragment",
        "https://provider.example:invalid/v1",
    ],
)
def test_onboarding_rejects_malformed_provider_urls_before_probe(
    monkeypatch, invalid_url
):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    probe = MagicMock()
    monkeypatch.setattr(model_manager, "probe_model_connection", probe)
    token = api_server.configure_api_token("invalid-url-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/onboard",
            json={
                "provider_model_id": "provider/model-v2",
                "nickname": "daily-coder",
                "api_key": "opaque-url-secret",
                "base_url": invalid_url,
            },
        )

    assert response.status_code == 422
    assert "opaque-url-secret" not in response.text
    probe.assert_not_called()


def test_unsaved_probe_uses_provider_id_and_redacts_provider_errors(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    observed = {}
    credential = "opaque-provider-credential"

    class Response:
        status_code = 418
        text = f"upstream echoed {credential}"

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            observed.update(url=url, json=json, headers=headers)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key=credential,
        base_url="https://provider.example/v1/",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is False
    assert credential not in result["error"]
    assert observed["url"] == "https://provider.example/v1/chat/completions"
    assert observed["json"]["model"] == "provider/model-v2"
    assert observed["headers"]["Authorization"] == f"Bearer {credential}"


def test_unsaved_probe_redacts_credentials_from_transport_exceptions(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    credential = "opaque-transport-credential"

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            raise RuntimeError(f"transport rejected {credential}")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key=credential,
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is False
    assert credential not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_unsaved_probe_never_sends_a_credential_over_plaintext_http(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    client = MagicMock(side_effect=AssertionError("network client must not open"))
    monkeypatch.setattr(model_manager.httpx, "Client", client)

    result = model_manager.probe_model_connection(
        api_key="fake-opaque-plaintext-credential",
        base_url="http://provider.example/v1",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is False
    assert "https://" in result["error"]
    assert "fake-opaque-plaintext-credential" not in result["error"]
    client.assert_not_called()


def test_legacy_addmodel_command_never_parses_or_persists_credentials(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    add = MagicMock()
    monkeypatch.setattr(model_manager, "add_model", add)
    token = api_server.configure_api_token("legacy-command-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/command",
            json={
                "command": "/addmodel provider sk-command-secret https://example.test alias"
            },
        )

    assert response.status_code == 200
    assert response.json()["action"] == "error"
    assert "sk-command-secret" not in response.text
    add.assert_not_called()


@pytest.mark.parametrize("command", ["/help", "/"])
def test_help_never_teaches_credential_bearing_model_commands(monkeypatch, command):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    token = api_server.configure_api_token("safe-help-token")

    with _client(api_server, token=token) as client:
        response = client.post("/command", json={"command": command})

    assert response.status_code == 200
    help_text = response.json()["message"]
    assert "/addmodel" in help_text
    assert "<key>" not in help_text
    assert "密钥不写入命令" in help_text


def test_preset_endpoint_exposes_connection_targets_without_model_ids(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    token = api_server.configure_api_token("presets-token")

    with _client(api_server, token=token) as client:
        response = client.get("/models/presets")

    assert response.status_code == 200
    presets = response.json()["presets"]
    assert presets
    for preset in presets:
        assert set(preset) == {"id", "name", "base_url", "category"}
        assert preset["base_url"].startswith("https://")
    # A preset must not smuggle a model id under any spelling.
    for forbidden in ("default_model_name", "modelId", "model_name", "provider_model_id"):
        assert forbidden not in response.text


def test_discovery_returns_provider_catalogue_without_persisting(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    discover = MagicMock(
        return_value={
            "success": True,
            "elapsed": 0.2,
            "models": [{"id": "deepseek-chat", "owned_by": "deepseek"}],
        }
    )
    add = MagicMock()
    activate = MagicMock()
    monkeypatch.setattr(model_manager, "discover_provider_models", discover)
    monkeypatch.setattr(model_manager, "add_model", add)
    monkeypatch.setattr(model_manager, "set_active_model", activate)
    token = api_server.configure_api_token("discover-success-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/discover",
            json={
                "api_key": "sk-discovery-secret",
                "base_url": "https://api.deepseek.com/v1/",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["models"] == [{"id": "deepseek-chat", "owned_by": "deepseek"}]
    assert "sk-discovery-secret" not in response.text
    discover.assert_called_once_with(
        api_key="sk-discovery-secret",
        base_url="https://api.deepseek.com/v1",
    )
    add.assert_not_called()
    activate.assert_not_called()


def test_failed_discovery_reports_400_and_redacts_the_credential(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    discover = MagicMock(
        return_value={"success": False, "error": "provider rejected opaqueDiscovery123"}
    )
    add = MagicMock()
    monkeypatch.setattr(model_manager, "discover_provider_models", discover)
    monkeypatch.setattr(model_manager, "add_model", add)
    token = api_server.configure_api_token("discover-failure-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/discover",
            json={
                "api_key": "opaqueDiscovery123",
                "base_url": "https://provider.example/v1",
            },
        )

    assert response.status_code == 400
    assert "opaqueDiscovery123" not in response.text
    add.assert_not_called()


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://provider.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?token=value",
    ],
)
def test_discovery_rejects_malformed_urls_before_any_request(monkeypatch, invalid_url):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    discover = MagicMock()
    monkeypatch.setattr(model_manager, "discover_provider_models", discover)
    token = api_server.configure_api_token("discover-url-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/discover",
            json={"api_key": "opaque-url-discovery-secret", "base_url": invalid_url},
        )

    assert response.status_code == 422
    assert "opaque-url-discovery-secret" not in response.text
    discover.assert_not_called()


def test_discovery_request_has_no_model_id_field(monkeypatch):
    """Discovery is for users who do not know a model id yet."""
    from RxyCode.RxyCode1_1_0 import api_server

    assert "provider_model_id" not in api_server.ModelDiscoveryRequest.model_fields


def test_model_listing_reports_real_switch_history(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {
            "models": {
                "alpha": {"model_name": "provider/alpha", "base_url": "https://a.example"},
                "beta": {"model_name": "provider/beta", "base_url": "https://b.example"},
            },
            "active_model": "beta",
            "recent_models": ["beta", "removed-model", "alpha"],
        },
    )
    token = api_server.configure_api_token("recent-history-token")

    with _client(api_server, token=token) as client:
        response = client.get("/models")

    assert response.status_code == 200
    # stale entries are pruned so the TUI never offers a deleted model
    assert response.json()["recent"] == ["beta", "alpha"]
