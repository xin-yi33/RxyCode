"""Behavioral security and model-onboarding contracts for the local API."""

import inspect
import json
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
                "Origin": "http://127.0.0.1:8765",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8765"


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
    # Config key is provider-namespaced so the same vendor id can live under
    # multiple endpoints; nickname remains the display alias.
    assert payload["model"]["id"] == "custom/provider/model-v2"
    assert payload["model"]["nickname"] == "daily-coder"
    assert payload["model"]["provider_model_id"] == "provider/model-v2"
    assert payload["model"]["provider_name"] == "其他"
    assert "sk-mapping-secret" not in response.text
    probe.assert_called_once_with(
        api_key="sk-mapping-secret",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )
    add.assert_called_once_with(
        "custom/provider/model-v2",
        "sk-mapping-secret",
        "https://provider.example/v1",
        model_name="provider/model-v2",
        provider_id="custom",
        provider_name="其他",
        nickname="daily-coder",
    )
    activate.assert_called_once_with("custom/provider/model-v2")


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
    assert observed["url"] == "https://provider.example/v1/responses"
    assert observed["json"]["model"] == "provider/model-v2"
    assert observed["json"]["input"] == "Hi"
    assert observed["headers"]["Authorization"] == f"Bearer {credential}"


def test_custom_probe_falls_back_to_chat_only_when_responses_endpoint_is_missing(
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0.config import model_manager

    observed = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            observed.append((url, json))
            if url.endswith("/responses"):
                return Response(404, {"error": {"message": "endpoint not found"}})
            return Response(
                200,
                {"choices": [{"message": {"content": "CHAT_OK"}}]},
            )

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="fake-key",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is True
    assert result["reply"] == "CHAT_OK"
    assert result["transport"] == "openai_chat"
    assert result.get("outcome") == "completed"
    assert [url.rsplit("/", 1)[-1] for url, _ in observed] == [
        "responses",
        "completions",
    ]


def test_custom_probe_does_not_hide_responses_policy_403_with_chat_fallback(
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0.config import model_manager

    calls = []

    class Response:
        status_code = 403
        text = '{"error":{"message":"DataPolicyError"}}'

        def json(self):
            return {"error": {"message": "DataPolicyError"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            calls.append(url)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="fake-key",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is False
    assert "403" in result["error"]
    assert calls == ["https://provider.example/v1/responses"]


def test_custom_probe_reports_when_neither_api_transport_exists(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    calls = []

    class Response:
        status_code = 404
        text = '{"error":{"message":"endpoint not found"}}'

        def json(self):
            return {"error": {"message": "endpoint not found"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            calls.append(url)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="fake-key",
        base_url="https://provider.example/v1",
        provider_model_id="provider/model-v2",
    )

    assert result["success"] is False
    assert result["error"] == (
        "No supported LLM API transport; attempted openai_responses, openai_chat"
    )
    assert calls == [
        "https://provider.example/v1/responses",
        "https://provider.example/v1/chat/completions",
    ]


def test_custom_probe_does_not_switch_interfaces_for_model_not_found_404(
    monkeypatch,
):
    from RxyCode.RxyCode1_1_0.config import model_manager

    calls = []

    class Response:
        status_code = 404
        text = '{"error":{"message":"model missing-model does not exist"}}'

        def json(self):
            return {"error": {"message": "model missing-model does not exist"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            calls.append(url)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="fake-key",
        base_url="https://provider.example/v1",
        provider_model_id="missing-model",
    )

    assert result["success"] is False
    assert "does not exist" in result["error"]
    assert calls == ["https://provider.example/v1/responses"]


def test_probe_surfaces_unsupported_model_instead_of_generic_401(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    class Response:
        status_code = 401
        text = '{"error":{"type":"ModelError","message":"Model mimo-v2.5 is not supported"}}'

        def json(self):
            return {
                "error": {
                    "type": "ModelError",
                    "message": "Model mimo-v2.5 is not supported",
                }
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="fake-key",
        base_url="https://opencode.ai/zen/v1",
        provider_model_id="mimo-v2.5",
    )
    assert result["success"] is False
    assert "not supported" in result["error"]
    assert "401" not in result["error"]


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
    assert "不会自动拉专家团" in help_text
    assert "/team <可拆任务>" in help_text
    assert "/children" in help_text


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
        return_value={
            "success": False,
            "error": "provider rejected opaqueDiscovery123",
            "error_code": "transport",
        }
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
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "transport"
    assert "discovery failed" in detail["message"].lower()
    add.assert_not_called()


def test_discover_failure_returns_structured_error_code(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    discover = MagicMock(
        return_value={
            "success": False,
            "error": "认证失败。API Key 可能错误或已过期。(HTTP 401 Unauthorized)",
            "error_code": "auth",
            "elapsed": 0.1,
        }
    )
    monkeypatch.setattr(model_manager, "discover_provider_models", discover)
    token = api_server.configure_api_token("discover-auth-code-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/discover",
            json={
                "api_key": "sk-wrong",
                "base_url": "https://provider.example/v1",
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "auth"
    assert "Discovery failed" in detail["message"] or "认证" in detail["message"]


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


def test_model_listing_includes_category_from_provider_name(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {
            "models": {
                "deepseek-chat": {
                    "model_name": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
                    "provider_name": "DeepSeek",
                },
                "legacy-model": {
                    "model_name": "legacy-model",
                    "base_url": "https://legacy.example/v1",
                },
            },
            "active_model": "deepseek-chat",
            "recent_models": [],
        },
    )
    token = api_server.configure_api_token("category-listing-token")

    with _client(api_server, token=token) as client:
        response = client.get("/models")

    assert response.status_code == 200
    models = {item["id"]: item for item in response.json()["models"]}
    assert models["deepseek-chat"]["category"] == "DeepSeek"
    assert models["legacy-model"]["category"] == "其他"


def test_batch_onboarding_adds_models_without_probe(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    probe = MagicMock()
    batch = MagicMock(
        return_value={
            "added": ["deepseek-chat", "deepseek-reasoner"],
            "skipped": [],
            "active": "deepseek-chat",
            "message": "Added 2 models",
        }
    )
    monkeypatch.setattr(model_manager, "probe_model_connection", probe)
    monkeypatch.setattr(model_manager, "onboard_models_batch", batch)
    token = api_server.configure_api_token("batch-onboard-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/onboard/batch",
            json={
                "api_key": "sk-batch-secret",
                "base_url": "https://api.deepseek.com/v1",
                "model_ids": ["deepseek-chat", "deepseek-reasoner"],
                "provider_id": "deepseek",
                "provider_name": "DeepSeek",
                "active_model_id": "deepseek-chat",
                "skip_probe": True,
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["action"] == "models_added"
    assert payload["added"] == ["deepseek-chat", "deepseek-reasoner"]
    assert payload["active"] == "deepseek-chat"
    assert "sk-batch-secret" not in response.text
    probe.assert_not_called()
    batch.assert_called_once_with(
        api_key="sk-batch-secret",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-chat", "deepseek-reasoner"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        active_model_id="deepseek-chat",
        skip_probe=True,
    )


def test_batch_onboarding_returns_400_when_nothing_added(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(
        model_manager,
        "onboard_models_batch",
        lambda **kwargs: {
            "added": [],
            "skipped": ["deepseek-chat"],
            "active": None,
            "message": "All models already exist",
        },
    )
    token = api_server.configure_api_token("batch-empty-token")

    with _client(api_server, token=token) as client:
        response = client.post(
            "/models/onboard/batch",
            json={
                "api_key": "sk-batch-empty",
                "base_url": "https://api.deepseek.com/v1",
                "model_ids": ["deepseek-chat"],
            },
        )

    assert response.status_code == 400
    assert "sk-batch-empty" not in response.text


def test_model_listing_includes_output_limit_summary(monkeypatch):
    """M6/M7：/models 响应含可选输出上限摘要，且不含 API key。"""
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {
            "models": {
                "deepseek/deepseek-v4-flash": {
                    "model_name": "deepseek-v4-flash",
                    "base_url": "https://api.deepseek.com/v1",
                    "provider_id": "deepseek",
                    "max_tokens": "auto",
                },
            },
            "active_model": "deepseek/deepseek-v4-flash",
            "recent_models": [],
            "model_limits": {
                "unknown_model_max_tokens": 32768,
                "context_safety_margin_tokens": 1024,
            },
        },
    )
    token = api_server.configure_api_token("summary-token")

    with _client(api_server, token=token) as client:
        response = client.get("/models")

    assert response.status_code == 200
    model = response.json()["models"][0]
    assert model["max_tokens_mode"] in ("auto", "explicit")
    assert isinstance(model.get("resolved_max_tokens"), int)
    assert model["resolved_max_tokens"] > 0
    assert model["limit_source"] in (
        "explicit_config", "catalog_exact_provider", "catalog_exact_model",
        "catalog_family", "provider_default", "unknown_fallback",
        "context_cap", "explicit_clamped", "legacy_server",
    )
    # API key 永不泄漏
    assert "api_key" not in response.text
    assert "sk-" not in response.text


def test_onboarding_error_trace_never_contains_api_key():
    """M7.4：异常消息与响应不含 API key/secret（覆盖 redact 行为）。"""
    from unittest.mock import patch

    from RxyCode.RxyCode1_1_0.config import model_manager

    secret = "sk-trace-secret-abcdef"
    # 真实 discover 内部用 safe_error() 对 api_key 做 redact；
    # 模拟传输异常路径（httpx.Client 抛错），验证返回的 error 不含 secret。
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = (
            RuntimeError(f"connection refused for {secret}")
        )
        result = model_manager.discover_provider_models(
            api_key=secret, base_url="https://api.example.com/v1"
        )
    assert "connection refused" in result.get("error", "")
    assert secret not in result.get("error", "")
    assert secret not in str(result)

    # safe_error redact：确认 discover 内部替换逻辑把 api_key 抹掉
    assert "[REDACTED]" in result.get("error", "")


def test_model_limits_inspect_never_leaks_credentials(monkeypatch):
    """M7.4：inspect 报告不含 api_key / secret / 环境变量值。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(
        model_manager,
        "load_config",
        lambda: {
            "models": {
                "demo/m": {
                    "model_name": "m", "base_url": "https://api.example.com/v1",
                    "provider_id": "demo", "api_key_env": "SECRET_ENV",
                },
            },
            "model_limits": {},
        },
    )
    report = model_manager.inspect_model_limits()
    text = str(report)
    assert "SECRET_ENV" not in text
    assert "api_key" not in text or "api_key_env" not in text.split(":")[0]
    assert "sk-" not in text


def test_models_and_inspect_never_leak_generic_secret_fields(monkeypatch):
    """M7.4：api_key 之外的通用 secret 字段（password/token/access_token/secret）
    也不得出现在 /models 响应或 inspect 报告中。"""
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.config import model_manager, settings

    secret_password = "super-secret-password-xyz"
    secret_token = "opaque-access-token-xyz"

    config = {
        "models": {
            "demo/m": {
                "model_name": "m",
                "base_url": "https://api.example.com/v1",
                "provider_id": "demo",
                "api_key_secret": "sk-stored-secret",
                "password": secret_password,
                "access_token": secret_token,
            },
        },
        "active_model": "demo/m",
        "recent_models": [],
        "model_limits": {},
    }

    # inspect 报告不泄漏
    monkeypatch.setattr(model_manager, "load_config", lambda: config)
    report_text = str(model_manager.inspect_model_limits())
    assert secret_password not in report_text
    assert secret_token not in report_text
    assert "sk-stored-secret" not in report_text

    # /models 响应不泄漏（含 password/token/secret 值）
    monkeypatch.setattr(api_server, "_init_agent", lambda: None)
    monkeypatch.setattr(settings, "load_config", lambda: config)
    token = api_server.configure_api_token("generic-secret-token")
    with _client(api_server, token=token) as client:
        response = client.get("/models")
    assert response.status_code == 200
    assert secret_password not in response.text
    assert secret_token not in response.text
    assert "sk-stored-secret" not in response.text
    assert "password" not in response.text
    assert "access_token" not in response.text
