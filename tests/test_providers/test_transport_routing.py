"""Generic Chat/Responses selection and safe endpoint fallback."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import get_args

import pytest
from langchain_core.messages import HumanMessage

from config.model_capabilities import DEFAULT_CAPABILITIES
from config.settings import resolve_model_config
from core import agent_v2
from core.agent_v2 import AgentV2
from core.providers import base as provider_base
from core.providers.base import BaseProvider
from core.providers.deepseek import DeepSeekProvider
from core.providers.doubao import DoubaoProvider
from core.providers.openai import OpenAIProvider
from core.providers.qwen import QwenProvider


class _HTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _RequestAwareHTTPError(_HTTPError):
    def __init__(self, status_code: int, message: str, request_url: str):
        super().__init__(status_code, message)
        self.request_url = request_url


def test_transport_contract_exposes_only_three_canonical_values():
    assert set(get_args(provider_base.LLMTransport)) == {
        "openai_chat",
        "openai_responses",
        "anthropic_messages",
    }


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("openai_chat", ("openai_chat",)),
        ("chat", ("openai_chat",)),
        ("openai_responses", ("openai_responses", "openai_chat")),
        ("responses", ("openai_responses", "openai_chat")),
        ("anthropic_messages", ("anthropic_messages",)),
    ],
)
def test_explicit_transport_accepts_canonical_and_legacy_values(
    configured, expected
):
    assert BaseProvider().transport_candidates(
        {"provider_id": "custom", "api_transport": configured}
    ) == expected


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [("chat", "openai_chat"), ("responses", "openai_responses")],
)
def test_runtime_config_migrates_legacy_transport_without_mutating_source(
    legacy, canonical
):
    stored = {"api_transport": legacy}
    resolved = resolve_model_config(stored)
    assert resolved["api_transport"] == canonical
    assert stored["api_transport"] == legacy


@pytest.mark.parametrize(
    ("resource_url", "transport"),
    [
        ("https://provider.example/v1/chat/completions", "openai_chat"),
        ("https://provider.example/v1/responses", "openai_responses"),
        ("https://provider.example/v1/messages", "anthropic_messages"),
    ],
)
def test_runtime_config_infers_explicit_resource_and_stores_only_api_root(
    resource_url, transport
):
    stored = {"base_url": resource_url}
    resolved = resolve_model_config(stored)
    assert resolved["base_url"] == "https://provider.example/v1"
    assert resolved["api_transport"] == transport
    assert stored == {"base_url": resource_url}


def test_invalid_explicit_transport_fails_closed():
    with pytest.raises(ValueError, match="api_transport"):
        BaseProvider().transport_candidates({"api_transport": "chatty"})


def test_candidate_normalization_is_stable_and_rejects_empty_input():
    normalizer = getattr(provider_base, "normalize_transport_candidates", None)
    assert callable(normalizer)
    assert normalizer(
        ["responses", "openai_responses", "chat", "openai_chat"]
    ) == ("openai_responses", "openai_chat")
    with pytest.raises(ValueError, match="at least one"):
        normalizer([])


@pytest.mark.parametrize(
    "provider_id",
    ["openrouter", "groq", "dashscope", "custom", "other"],
)
def test_audited_and_custom_presets_prefer_responses(provider_id):
    assert BaseProvider().transport_candidates({"provider_id": provider_id}) == (
        "openai_responses",
        "openai_chat",
    )


@pytest.mark.parametrize(
    "provider_id",
    [
        "moonshot",
        "zhipu",
        "siliconflow",
        "zen",
        "opencode-go",
        "together",
    ],
)
def test_unverified_or_chat_only_presets_stay_on_chat(provider_id):
    assert BaseProvider().transport_candidates({"provider_id": provider_id}) == (
        "openai_chat",
    )


def test_explicit_chat_is_a_non_fallback_compatibility_switch():
    assert BaseProvider().transport_candidates(
        {"provider_id": "custom", "api_transport": "chat"}
    ) == ("openai_chat",)


def test_responses_first_policy_is_forwarded_to_langchain_openai():
    cfg = {
        "provider_id": "custom",
        "model_name": "custom-model",
        "base_url": "https://custom.invalid/v1",
        "resolved_max_tokens": 32,
    }
    kwargs = BaseProvider().llm_kwargs(cfg, DEFAULT_CAPABILITIES)
    assert kwargs["use_responses_api"] is True


def test_responses_path_does_not_inject_chat_thinking_parameter():
    caps = replace(
        DEFAULT_CAPABILITIES,
        supports_reasoning=True,
        thinking_default_on=True,
        effort_presets={"balanced": "high"},
    )
    kwargs = BaseProvider().llm_kwargs(
        {
            "provider_id": "custom",
            "model_name": "reasoning-model",
            "base_url": "https://gateway.example/v1",
            "resolved_max_tokens": 32,
            "effort": "balanced",
        },
        caps,
    )
    assert kwargs["use_responses_api"] is True
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert kwargs["reasoning_effort"] == "high"


def test_chat_only_policy_does_not_enable_responses_in_langchain_openai():
    cfg = {
        "provider_id": "opencode-go",
        "model_name": "hy3",
        "base_url": "https://opencode.ai/zen/go/v1",
        "resolved_max_tokens": 32,
    }
    kwargs = BaseProvider().llm_kwargs(cfg, DEFAULT_CAPABILITIES)
    assert "use_responses_api" not in kwargs


def test_official_response_hosts_prefer_responses_without_saved_preset_metadata():
    assert OpenAIProvider().transport_candidates(
        {"base_url": "https://api.openai.com/v1"}
    ) == ("openai_responses", "openai_chat")
    assert DeepSeekProvider().transport_candidates(
        {"base_url": "https://api.deepseek.com/v1"}
    ) == ("openai_chat",)
    assert DoubaoProvider().transport_candidates(
        {"base_url": "https://ark.cn-beijing.volces.com/api/v3"}
    ) == ("openai_responses", "openai_chat")
    assert QwenProvider().transport_candidates(
        {
            "base_url": (
                "https://workspace.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            )
        }
    ) == ("openai_responses", "openai_chat")


@pytest.mark.parametrize(
    "configured_url",
    [
        "https://dashscope.aliyuncs.com.attacker.example/compatible-mode/v1",
        "https://dashscope.aliyuncs.com@attacker.example/compatible-mode/v1",
        "https://maas.aliyuncs.com.attacker.example/compatible-mode/v1",
    ],
)
def test_qwen_response_host_check_rejects_spoofs(configured_url):
    assert QwenProvider().transport_candidates({"base_url": configured_url}) == (
        "openai_chat",
    )


@pytest.mark.parametrize("status", [404, 405])
def test_only_endpoint_mismatch_statuses_allow_fallback(status):
    provider = BaseProvider()
    assert provider.should_fallback_transport(
        _HTTPError(status, "endpoint unavailable"),
        from_transport="openai_responses",
        to_transport="openai_chat",
    )


@pytest.mark.parametrize(
    "message",
    ["Not Found", '{"detail":"Not Found"}', "Invalid URL (POST /v1/responses)"],
)
def test_generic_missing_responses_resource_uses_request_path_as_transport_evidence(
    message,
):
    provider = BaseProvider()
    assert provider.should_fallback_transport(
        _RequestAwareHTTPError(404, message, "https://gateway.example/v1/responses"),
        from_transport="openai_responses",
        to_transport="openai_chat",
    )


def test_resource_not_found_remains_a_non_transport_error_even_with_request_path():
    provider = BaseProvider()
    assert not provider.should_fallback_transport(
        _RequestAwareHTTPError(
            404,
            "resource not found",
            "https://gateway.example/v1/responses",
        ),
        from_transport="openai_responses",
        to_transport="openai_chat",
    )


@pytest.mark.parametrize(
    "message",
    [
        "model custom-model does not exist",
        "No such model custom-model",
        "requested model custom-model could not be found",
    ],
)
def test_model_not_found_is_not_misclassified_as_an_endpoint_error(message):
    provider = BaseProvider()
    assert not provider.should_fallback_transport(
        _HTTPError(404, message),
        from_transport="openai_responses",
        to_transport="openai_chat",
    )


@pytest.mark.parametrize("status", [401, 403, 408, 429, 500, 502, 503, 504])
def test_auth_policy_rate_timeout_and_server_errors_never_fallback(status):
    provider = BaseProvider()
    assert not provider.should_fallback_transport(
        _HTTPError(status, "DataPolicyError or ordinary provider failure"),
        from_transport="openai_responses",
        to_transport="openai_chat",
    )


@pytest.mark.parametrize(
    ("status", "message", "expected", "expected_class"),
    [
        (404, "resource not found", False, "UNKNOWN"),
        (404, "endpoint not found", True, "TRANSPORT_UNSUPPORTED"),
        (404, "route not found", True, "TRANSPORT_UNSUPPORTED"),
        (400, "unsupported endpoint parameter", False, "REQUEST_VALIDATION"),
        (400, "parameter endpoint is not supported", False, "REQUEST_VALIDATION"),
        (400, "protocol not supported", True, "TRANSPORT_UNSUPPORTED"),
        (400, "Responses API is not supported", True, "TRANSPORT_UNSUPPORTED"),
        (
            400,
            "This model does not support the Responses API",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (
            400,
            "This model does not support Chat Completions API",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (400, "use /chat/completions instead", True, "TRANSPORT_UNSUPPORTED"),
        (404, "No such model", False, "MODEL_ERROR"),
        (404, "requested model could not be found", False, "MODEL_ERROR"),
        (400, "invalid tool schema", False, "REQUEST_VALIDATION"),
        (400, "API key format not supported", False, "AUTH_OR_POLICY"),
        (404, "credential not found in API", False, "AUTH_OR_POLICY"),
        (404, "object not found in API", False, "REQUEST_VALIDATION"),
        (
            400,
            "authentication method not supported by API",
            False,
            "AUTH_OR_POLICY",
        ),
        (400, "parameter not found in API", False, "REQUEST_VALIDATION"),
        (400, "API endpoint is not supported", True, "TRANSPORT_UNSUPPORTED"),
        (404, "API route not found", True, "TRANSPORT_UNSUPPORTED"),
        (400, "Chat Completions API unavailable", True, "TRANSPORT_UNSUPPORTED"),
        (
            400,
            "endpoint is not supported for this model",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (
            400,
            "Responses API is not supported for model X",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (
            400,
            "API endpoint unavailable for model X",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (
            404,
            "route does not exist for the requested model",
            True,
            "TRANSPORT_UNSUPPORTED",
        ),
        (
            404,
            "requested model not found at this endpoint",
            False,
            "MODEL_ERROR",
        ),
        (
            400,
            "model X does not support parameter temperature",
            False,
            "REQUEST_VALIDATION",
        ),
        (400, "invalid model for Responses API", False, "MODEL_ERROR"),
        (
            400,
            "tool schema is not supported by this model",
            False,
            "REQUEST_VALIDATION",
        ),
    ],
)
def test_endpoint_fallback_requires_explicit_transport_evidence(
    status, message, expected, expected_class
):
    provider = BaseProvider()
    error = _HTTPError(status, message)
    classification = provider_base._classify_transport_error(error)
    assert classification.value == expected_class
    assert provider.should_fallback_transport(
        error,
        from_transport="openai_responses",
        to_transport="openai_chat",
    ) is expected


def _agent(provider, responses_llm, chat_create):
    cfg = {
        "provider_id": "custom",
        "base_url": "https://custom.invalid/v1",
        "model_name": "custom-model",
        "resolved_max_tokens": 8,
        "timeout": 5.0,
    }
    agent = object.__new__(AgentV2)
    agent._session_id = "transport-test"
    agent.model_config = cfg
    agent._provider = provider
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._llm = SimpleNamespace(_llm=responses_llm)
    agent._rate_limiter = None
    agent._thinking_disabled_this_turn = False
    agent._openai_client = lambda: SimpleNamespace(create=chat_create)
    return agent


def _chat_success(**payload):
    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="CHAT_OK", reasoning_content="", tool_calls=[]
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    assert "messages" in payload
    return stream()


@pytest.mark.asyncio
async def test_endpoint_404_before_output_falls_back_from_responses_to_chat(monkeypatch):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )

    class Responses404:
        async def astream(self, messages, **kwargs):
            raise _HTTPError(404, "Responses endpoint not found")
            yield  # pragma: no cover

    agent = _agent(BaseProvider(), Responses404(), _chat_success)
    chunks = [
        chunk
        async for chunk in agent._raw_stream(
            [HumanMessage(content="hi")], max_tokens=8
        )
    ]
    assert chunks[-1].choices[0].delta.content == "CHAT_OK"


@pytest.mark.asyncio
async def test_policy_403_does_not_fallback(monkeypatch):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )
    chat_called = False

    class Responses403:
        async def astream(self, messages, **kwargs):
            raise _HTTPError(403, "DataPolicyError")
            yield  # pragma: no cover

    def chat_create(**payload):
        nonlocal chat_called
        chat_called = True
        return _chat_success(**payload)

    agent = _agent(BaseProvider(), Responses403(), chat_create)
    with pytest.raises(_HTTPError, match="DataPolicyError"):
        _ = [
            chunk
            async for chunk in agent._raw_stream(
                [HumanMessage(content="hi")], max_tokens=8
            )
        ]
    assert chat_called is False


@pytest.mark.asyncio
async def test_failure_after_useful_output_never_falls_back(monkeypatch):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )
    chat_called = False

    class PartialThen404:
        async def astream(self, messages, **kwargs):
            yield SimpleNamespace(
                content=[{"type": "text", "text": "PARTIAL"}],
                tool_call_chunks=[],
                usage_metadata=None,
                chunk_position=None,
                response_metadata={},
            )
            raise _HTTPError(404, "endpoint disappeared")

    def chat_create(**payload):
        nonlocal chat_called
        chat_called = True
        return _chat_success(**payload)

    agent = _agent(BaseProvider(), PartialThen404(), chat_create)
    seen = []
    with pytest.raises(_HTTPError, match="endpoint disappeared"):
        async for chunk in agent._raw_stream(
            [HumanMessage(content="hi")], max_tokens=8
        ):
            seen.append(chunk.choices[0].delta.content)
    assert seen == ["PARTIAL"]
    assert chat_called is False


@pytest.mark.asyncio
async def test_both_unsupported_transports_return_combined_error(monkeypatch):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )

    class Responses404:
        async def astream(self, messages, **kwargs):
            raise _HTTPError(404, "Responses API is not supported")
            yield  # pragma: no cover

    def chat_404(**payload):
        async def stream():
            raise _HTTPError(405, "Chat Completions API unavailable")
            yield  # pragma: no cover

        return stream()

    agent = _agent(BaseProvider(), Responses404(), chat_404)
    with pytest.raises(
        RuntimeError, match="attempted: openai_responses, openai_chat"
    ):
        _ = [
            chunk
            async for chunk in agent._raw_stream(
                [HumanMessage(content="hi")], max_tokens=8
            )
        ]
