"""Canonical API-root normalization for all LLM transports."""

from __future__ import annotations

import httpx
import pytest
from uuid import uuid4

from config.model_endpoint import (
    detect_explicit_transport,
    infer_transport_from_resource_path,
    llm_client_base_url,
    llm_endpoint_url,
    normalize_llm_endpoint,
    normalize_resource_path,
    resource_path_request_hook,
    rewrite_sdk_request_url,
)


@pytest.mark.parametrize(
    ("configured_url", "transport", "root", "endpoint"),
    [
        (
            "https://provider.example/v1/chat",
            "openai_chat",
            "https://provider.example/v1",
            "https://provider.example/v1/chat/completions",
        ),
        (
            "https://gateway.example/api/chat",
            "openai_chat",
            "https://gateway.example/api",
            "https://gateway.example/api/chat/completions",
        ),
        (
            "https://provider.example/v1/chat/completions/",
            "openai_chat",
            "https://provider.example/v1",
            "https://provider.example/v1/chat/completions",
        ),
        (
            "https://provider.example/v1/responses",
            "openai_responses",
            "https://provider.example/v1",
            "https://provider.example/v1/responses",
        ),
        (
            "https://provider.example/v1/messages",
            "anthropic_messages",
            "https://provider.example/v1",
            "https://provider.example/v1/messages",
        ),
        (
            "https://opencode.ai/zen/go/v1/responses",
            "openai_responses",
            "https://opencode.ai/zen/go/v1",
            "https://opencode.ai/zen/go/v1/responses",
        ),
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1/responses/",
            "openai_responses",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/responses",
        ),
    ],
)
def test_normalization_removes_only_the_matching_terminal_resource(
    configured_url, transport, root, endpoint
):
    assert normalize_llm_endpoint(configured_url, transport) == root
    assert llm_endpoint_url(configured_url, transport) == endpoint
    # Probe and the official OpenAI SDK must hit the same final resource.
    if transport == "openai_chat":
        assert llm_client_base_url(configured_url, transport) + "/chat/completions" == (
            endpoint
        )
    elif transport == "openai_responses":
        assert llm_client_base_url(configured_url, transport) + "/responses" == endpoint


@pytest.mark.parametrize(
    ("configured_url", "expected"),
    [
        ("https://provider.example/v1/CHAT/COMPLETIONS/", "openai_chat"),
        ("https://provider.example/v1/chat", "openai_chat"),
        ("https://provider.example/v1/Responses", "openai_responses"),
        ("https://provider.example/v1/Messages/", "anthropic_messages"),
        ("https://provider.example/v1/myresponses", None),
        ("https://provider.example/v1/chatty", None),
    ],
)
def test_explicit_resource_detection_is_case_insensitive_and_exact(
    configured_url, expected
):
    assert detect_explicit_transport(configured_url) == expected


@pytest.mark.parametrize(
    ("configured_url", "transport"),
    [
        ("https://provider.example/v1/responses", "openai_chat"),
        ("https://provider.example/v1/messages", "openai_responses"),
        ("https://provider.example/v1/chat/completions", "anthropic_messages"),
    ],
)
def test_explicit_resource_conflict_fails_before_network(configured_url, transport):
    with pytest.raises(ValueError, match="conflicts"):
        normalize_llm_endpoint(configured_url, transport)


@pytest.mark.parametrize(
    "configured_url",
    [
        "https://user@provider.example/v1",
        "https://provider.example/v1?mode=test",
        "https://provider.example/v1#fragment",
        "https://provider.example:bad/v1",
        "https://provider.example/v1 with-space",
    ],
)
def test_unsafe_or_ambiguous_urls_are_rejected(configured_url):
    with pytest.raises(ValueError, match="base_url"):
        normalize_llm_endpoint(configured_url, "openai_chat")


def test_plain_http_is_rejected_when_a_credential_will_be_sent():
    with pytest.raises(ValueError, match="https"):
        normalize_llm_endpoint(
            "http://provider.example/v1",
            "openai_chat",
            require_https=True,
        )


def test_anthropic_sdk_receives_service_root_but_config_keeps_api_root():
    api_root = "https://provider.example/gateway/v1/messages"
    assert normalize_llm_endpoint(api_root, "anthropic_messages") == (
        "https://provider.example/gateway/v1"
    )
    assert llm_client_base_url(api_root, "anthropic_messages") == (
        "https://provider.example/gateway"
    )


def test_similar_suffix_is_preserved_as_part_of_the_api_root():
    base_url = "https://provider.example/gateway/responses-v2"
    assert normalize_llm_endpoint(base_url, "openai_responses") == base_url
    assert llm_endpoint_url(base_url, "openai_responses") == (
        "https://provider.example/gateway/responses-v2/responses"
    )


@pytest.mark.parametrize(
    ("configured_url", "expected_url", "expected_transport", "payload"),
    [
        (
            "https://provider.example/v1/responses",
            "https://provider.example/v1/responses",
            "openai_responses",
            {"output_text": "OK"},
        ),
        (
            "https://provider.example/v1/chat/completions",
            "https://provider.example/v1/chat/completions",
            "openai_chat",
            {"choices": [{"message": {"content": "OK"}}]},
        ),
    ],
)
def test_custom_probe_does_not_duplicate_an_explicit_resource(
    monkeypatch, configured_url, expected_url, expected_transport, payload
):
    from config import model_manager

    observed: list[str] = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            del json, headers
            observed.append(url)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    credential = "test-" + uuid4().hex
    result = model_manager.probe_model_connection(
        api_key=credential,
        base_url=configured_url,
        provider_model_id="provider/model",
    )

    assert result["success"] is True
    assert result["transport"] == expected_transport
    assert observed == [expected_url]


def test_anthropic_probe_uses_native_messages_auth_and_validates_reply(monkeypatch):
    from config import model_manager

    observed: dict = {}

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "id": "msg_probe",
                "content": [{"type": "text", "text": "ANTHROPIC_OK"}],
            }

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
    credential = "test-" + uuid4().hex
    result = model_manager.probe_model_connection(
        api_key=credential,
        base_url="https://api.anthropic.com/v1",
        provider_model_id="claude-haiku-4-5",
    )

    assert result["success"] is True
    assert result["transport"] == "anthropic_messages"
    assert result["reply"] == "ANTHROPIC_OK"
    assert observed["url"] == "https://api.anthropic.com/v1/messages"
    assert observed["json"]["messages"] == [
        {"role": "user", "content": "Hi"}
    ]
    assert observed["headers"]["x-api-key"] == credential
    assert observed["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in observed["headers"]


@pytest.mark.parametrize(
    ("configured_url", "payload"),
    [
        ("https://provider.example/v1", {"id": "resp_missing_output"}),
        ("https://provider.example/v1/chat", {"id": "chat_missing_choices"}),
    ],
)
def test_probe_rejects_http_200_without_transport_reply_body(
    monkeypatch, configured_url, payload
):
    from config import model_manager

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, *, json, headers):
            del json, headers
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="test-" + uuid4().hex,
        base_url=configured_url,
        provider_model_id="provider/model",
    )

    assert result["success"] is False
    assert "no valid" in result["error"]


def test_probe_rejects_failed_responses_status(monkeypatch):
    from config import model_manager

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "failed", "output": []}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, *, json, headers):
            del json, headers
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="test-" + uuid4().hex,
        base_url="https://provider.example/v1/responses",
        provider_model_id="provider/model",
    )
    assert result["success"] is False


def test_probe_accepts_completed_response_without_visible_text(monkeypatch):
    from config import model_manager

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "content": [{"type": "reasoning_text", "text": "plan"}],
                    }
                ],
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, *, json, headers):
            del json, headers
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="test-" + uuid4().hex,
        base_url="https://provider.example/v1/responses",
        provider_model_id="provider/model",
    )
    assert result["success"] is True
    assert result["reply"] is None
    assert result["outcome"] == "completed_no_text"


def test_add_model_persists_api_root_and_explicit_transport(monkeypatch):
    from config import model_manager

    config = {"models": {}}
    saved: list[dict] = []
    monkeypatch.setattr(model_manager, "load_config", lambda: config)
    monkeypatch.setattr(model_manager, "save_config", lambda value: saved.append(value))
    monkeypatch.setattr(
        model_manager,
        "_credential_config",
        lambda _value: {"api_key_env": "RXYCODE_TEST_ENDPOINT_KEY"},
    )

    entry = model_manager.add_model(
        "custom/model",
        "test-" + uuid4().hex,
        "https://provider.example/gateway/v1/responses",
        model_name="custom/model",
        provider_id="custom",
        provider_name="Other",
    )

    assert entry["base_url"] == "https://provider.example/gateway/v1"
    assert entry["api_transport"] == "openai_responses"
    assert "api_key" not in entry
    assert saved == [config]


def test_batch_probe_preserves_explicit_resource_policy(monkeypatch):
    from config import model_manager

    probes: list[str] = []
    additions: list[dict] = []
    monkeypatch.setattr(model_manager, "load_config", lambda: {"models": {}})
    monkeypatch.setattr(
        model_manager,
        "resolve_provider_meta",
        lambda *_args, **_kwargs: {"id": "custom", "name": "Other"},
    )
    monkeypatch.setattr(
        model_manager,
        "probe_model_connection",
        lambda **kwargs: probes.append(kwargs["base_url"]) or {"success": True},
    )
    def add_model(name, api_key, base_url, **kwargs):
        del api_key
        addition = {"name": name, "base_url": base_url, **kwargs}
        additions.append(addition)
        return addition

    monkeypatch.setattr(model_manager, "add_model", add_model)
    monkeypatch.setattr(model_manager, "set_active_model", lambda _name: None)

    result = model_manager.onboard_models_batch(
        api_key="test-" + uuid4().hex,
        base_url="https://provider.example/gateway/v1/chat/completions",
        model_ids=["provider/model"],
        provider_id="custom",
        provider_name="Other",
        skip_probe=False,
    )

    assert result["added"] == ["custom/provider/model"]
    assert probes == ["https://provider.example/gateway/v1/chat/completions"]
    assert additions[0]["base_url"] == "https://provider.example/gateway/v1"
    assert additions[0]["api_transport"] == "openai_chat"


def test_resource_path_keeps_exact_chat_endpoint():
    root = "https://gateway.example/api"
    assert normalize_resource_path("/chat") == "/chat"
    assert infer_transport_from_resource_path("/chat") == "openai_chat"
    probe = llm_endpoint_url(root, "openai_chat", resource_path="/chat")
    runtime = rewrite_sdk_request_url(
        llm_client_base_url(root, "openai_chat") + "/chat/completions",
        resource_path="/chat",
        transport="openai_chat",
    )
    assert probe == "https://gateway.example/api/chat"
    assert runtime == probe


def test_resource_path_probe_hits_exact_chat_url(monkeypatch):
    from config import model_manager
    from core.providers.base import BaseProvider

    observed: list[str] = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            del json, headers
            observed.append(url)
            return Response()

    monkeypatch.setattr(model_manager.httpx, "Client", Client)
    result = model_manager.probe_model_connection(
        api_key="test-" + uuid4().hex,
        base_url="https://gateway.example/api",
        provider_model_id="custom-model",
        resource_path="/chat",
    )
    assert result["success"] is True
    assert result["transport"] == "openai_chat"
    assert observed == ["https://gateway.example/api/chat"]
    assert BaseProvider().transport_candidates(
        {
            "base_url": "https://gateway.example/api",
            "resource_path": "/chat",
            "provider_id": "custom",
        }
    ) == ("openai_chat",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "sdk_url", "resource_path", "expected"),
    [
        (
            "openai_chat",
            "https://gateway.example/api/chat/completions",
            "/chat",
            "https://gateway.example/api/chat",
        ),
        (
            "openai_responses",
            "https://gateway.example/api/responses",
            "/proxy/responses",
            "https://gateway.example/api/proxy/responses",
        ),
    ],
)
async def test_resource_path_async_client_reaches_rewritten_path(
    transport, sdk_url, resource_path, expected
):
    """httpx.AsyncClient awaits request hooks; a sync hook never hits the wire."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True}, request=request)

    hook = resource_path_request_hook(resource_path, transport)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [hook]},
    ) as client:
        response = await client.post(sdk_url, json={"model": "x"})
        assert response.status_code == 200
    assert seen == [expected]


@pytest.mark.asyncio
async def test_chatopenai_resource_path_hook_reaches_exact_chat_path(monkeypatch):
    from langchain_openai import ChatOpenAI

    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "x",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            request=request,
        )

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-" + uuid4().hex)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={
            "request": [resource_path_request_hook("/chat", "openai_chat")]
        },
    )
    llm = ChatOpenAI(
        model="x",
        api_key="sk-test",
        base_url="https://gateway.example/api",
        http_async_client=client,
    )
    try:
        message = await llm.ainvoke("hi")
    finally:
        await client.aclose()
    assert message.content == "ok"
    assert seen, "request never reached the transport"
    assert seen[0].split("?", 1)[0] == "https://gateway.example/api/chat"


def test_add_model_rejects_anthropic_resource_path(monkeypatch):
    from config import model_manager

    monkeypatch.setattr(model_manager, "load_config", lambda: {"models": {}})
    monkeypatch.setattr(model_manager, "save_config", lambda _value: None)
    monkeypatch.setattr(
        model_manager,
        "_credential_config",
        lambda _value: {"api_key_env": "RXYCODE_TEST_ENDPOINT_KEY"},
    )
    with pytest.raises(ValueError, match="anthropic_messages"):
        model_manager.add_model(
            "anthropic/custom",
            "test-" + uuid4().hex,
            "https://gateway.example/api",
            model_name="claude-sonnet-4-5",
            provider_id="anthropic",
            api_transport="anthropic_messages",
            resource_path="/proxy/messages",
        )


def test_probe_rejects_anthropic_resource_path():
    from config import model_manager

    result = model_manager.probe_model_connection(
        api_key="test-" + uuid4().hex,
        base_url="https://gateway.example/api",
        provider_model_id="claude-sonnet-4-5",
        resource_path="/proxy/messages",
    )
    assert result["success"] is False
    assert "anthropic_messages" in result["error"]


def test_resource_path_candidates_reject_anthropic_custom_path():
    from core.providers.base import BaseProvider

    with pytest.raises(ValueError, match="anthropic_messages"):
        BaseProvider()._resource_path_candidates(
            {
                "api_transport": "anthropic_messages",
                "resource_path": "/proxy/messages",
            }
        )
