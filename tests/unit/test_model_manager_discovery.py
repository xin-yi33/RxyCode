"""Provider preset and model-discovery contracts for config.model_manager.

Discovery exists so a user never has to know a provider model id in advance:
presets carry only provider + base URL, and ids come from the live catalogue.
"""

from unittest.mock import MagicMock

import pytest


def _stub_client(monkeypatch, model_manager, *, response=None, raises=None, observed=None):
    """Replace httpx.Client with a recording double (no sockets in unit tests)."""

    class Client:
        def __init__(self, **kwargs):
            if observed is not None:
                observed["client_kwargs"] = kwargs

        def __enter__(self):
            if raises is not None:
                raise raises
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, *, headers):
            if observed is not None:
                observed.update(url=url, headers=headers)
            return response

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    return Client


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# ── presets ─────────────────────────────────────────────────────────


def test_presets_expose_provider_and_url_only():
    from RxyCode.RxyCode1_1_0.config import model_manager

    presets = model_manager.list_provider_presets()

    assert presets, "at least one connection preset must ship"
    for preset in presets:
        assert set(preset) == {"id", "name", "base_url", "category"}
        assert preset["base_url"].startswith("https://")


@pytest.mark.parametrize(
    "forbidden_key",
    ["default_model_name", "modelId", "model_name", "model", "provider_model_id"],
)
def test_presets_never_pin_a_model_id(forbidden_key):
    from RxyCode.RxyCode1_1_0.config import model_manager

    for preset in model_manager.list_provider_presets():
        assert forbidden_key not in preset


def test_preset_listing_cannot_mutate_the_module_table():
    from RxyCode.RxyCode1_1_0.config import model_manager

    first = model_manager.list_provider_presets()
    first[0]["base_url"] = "https://tampered.example"
    first[0]["default_model_name"] = "doubao-lite-32k"

    second = model_manager.list_provider_presets()
    assert second[0]["base_url"] != "https://tampered.example"
    assert "default_model_name" not in second[0]


# ── discovery: success paths ────────────────────────────────────────


def test_discovery_parses_openai_style_catalogue(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    observed: dict = {}
    credential = "fake-discovery-credential"
    payload = {
        "object": "list",
        "data": [
            {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
            {"id": "deepseek-reasoner", "object": "model"},
        ],
    }
    _stub_client(
        monkeypatch,
        model_manager,
        response=_Response(200, payload),
        observed=observed,
    )

    result = model_manager.discover_provider_models(
        api_key=credential,
        base_url="https://api.deepseek.com/v1/",
    )

    assert result["success"] is True
    assert result["models"] == [
        {"id": "deepseek-chat", "owned_by": "deepseek"},
        {"id": "deepseek-reasoner"},
    ]
    assert observed["url"] == "https://api.deepseek.com/v1/models"
    assert observed["headers"]["Authorization"] == f"Bearer {credential}"
    assert "elapsed" in result


def test_discovery_accepts_bare_list_and_string_entries(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _stub_client(
        monkeypatch,
        model_manager,
        response=_Response(200, ["glm-4", {"id": "glm-4"}, {"name": "glm-4-air"}]),
    )

    result = model_manager.discover_provider_models(
        api_key="fake-shape-credential",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    assert result["success"] is True
    # duplicate ids collapse, and `name` is accepted as an id fallback
    assert result["models"] == [{"id": "glm-4"}, {"id": "glm-4-air"}]


def test_discovery_uses_the_same_timeout_budget_as_the_chat_probe(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    observed: dict = {}
    _stub_client(
        monkeypatch,
        model_manager,
        response=_Response(200, {"data": [{"id": "a"}]}),
        observed=observed,
    )

    model_manager.discover_provider_models(
        api_key="fake-timeout-credential",
        base_url="https://provider.example/v1",
    )

    assert observed["client_kwargs"]["timeout"] == 30


# ── discovery: failure paths ────────────────────────────────────────


def test_discovery_reports_authentication_failure(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _stub_client(monkeypatch, model_manager, response=_Response(401, text="nope"))

    result = model_manager.discover_provider_models(
        api_key="fake-401-credential",
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    assert "401" in result["error"]
    assert "models" not in result


@pytest.mark.parametrize("status", [404, 405])
def test_discovery_guides_to_manual_entry_when_catalogue_is_absent(monkeypatch, status):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _stub_client(monkeypatch, model_manager, response=_Response(status, text="missing"))

    result = model_manager.discover_provider_models(
        api_key="fake-absent-credential",
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    assert result["error"] == model_manager.DISCOVERY_UNSUPPORTED_MESSAGE


def test_discovery_treats_an_empty_or_unparsable_catalogue_as_unsupported(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _stub_client(monkeypatch, model_manager, response=_Response(200, {"data": []}))
    empty = model_manager.discover_provider_models(
        api_key="fake-empty-credential",
        base_url="https://provider.example/v1",
    )

    _stub_client(
        monkeypatch,
        model_manager,
        response=_Response(200, ValueError("not json")),
    )
    unparsable = model_manager.discover_provider_models(
        api_key="fake-parse-credential",
        base_url="https://provider.example/v1",
    )

    assert empty["success"] is False
    assert empty["error"] == model_manager.DISCOVERY_UNSUPPORTED_MESSAGE
    assert unparsable["success"] is False
    assert unparsable["error"] == model_manager.DISCOVERY_UNSUPPORTED_MESSAGE


def test_discovery_maps_a_timeout_to_an_operator_readable_message(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _stub_client(
        monkeypatch,
        model_manager,
        raises=RuntimeError("Connection timed out"),
    )

    result = model_manager.discover_provider_models(
        api_key="fake-timeout-error-credential",
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    assert "超时" in result["error"]


# ── discovery: credential hygiene ───────────────────────────────────


def test_discovery_redacts_the_credential_from_provider_echoes(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    credential = "fake-echoed-credential"
    _stub_client(
        monkeypatch,
        model_manager,
        response=_Response(418, text=f"upstream echoed {credential}"),
    )

    result = model_manager.discover_provider_models(
        api_key=credential,
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    assert credential not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_discovery_redacts_the_credential_from_transport_exceptions(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    credential = "fake-transport-discovery-credential"
    _stub_client(
        monkeypatch,
        model_manager,
        raises=RuntimeError(f"transport rejected {credential}"),
    )

    result = model_manager.discover_provider_models(
        api_key=credential,
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    assert credential not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_discovery_never_sends_a_credential_over_plaintext_http(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    client = MagicMock(side_effect=AssertionError("network client must not open"))
    monkeypatch.setattr(model_manager.httpx, "Client", client)

    result = model_manager.discover_provider_models(
        api_key="fake-opaque-plaintext-discovery-credential",
        base_url="http://provider.example/v1",
    )

    assert result["success"] is False
    assert "https://" in result["error"]
    assert "fake-opaque-plaintext-discovery-credential" not in result["error"]
    client.assert_not_called()


def test_discovery_requires_a_credential_before_touching_the_network(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    client = MagicMock(side_effect=AssertionError("network client must not open"))
    monkeypatch.setattr(model_manager.httpx, "Client", client)

    result = model_manager.discover_provider_models(
        api_key="   ",
        base_url="https://provider.example/v1",
    )

    assert result["success"] is False
    client.assert_not_called()
