"""Muse Spark provider and OpenCode Go Responses transport contracts."""

from __future__ import annotations

from types import SimpleNamespace
import json
import uuid

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_responses_chunk_to_generation_chunk,
)
from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseTextDeltaEvent,
)

from config.model_capabilities import DEFAULT_CAPABILITIES
from core import providers
from core.agent_v2 import AgentV2, UsageTrackingLLM
from core.providers.hy3 import Hy3Provider
from core.providers.muse_spark import MuseSparkProvider


_GO = "https://opencode.ai/zen/go/v1"
_GO_PUBLIC_MUSE_MODELS_AS_OF_2026_08_24 = frozenset(
    {"muse-spark-1.2-contributor"}
)


def _config(model: str = "muse-spark-1.2-contributor", **extra):
    return {
        "base_url": _GO,
        "model_name": model,
        "resolved_max_tokens": 8192,
        **extra,
    }


def _responses_base(status: str, *, output=None, usage=None, error=None, **extra):
    response = {
        "id": "resp_test",
        "created_at": 0.0,
        "model": "muse-spark-1.2-contributor",
        "object": "response",
        "output": output or [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": status,
        **extra,
    }
    if usage is not None:
        response["usage"] = usage
    if error is not None:
        response["error"] = error
    return response


def _responses_sse(*events: dict) -> bytes:
    parts = []
    for event in events:
        parts.append(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n")
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


def _mock_responses_llm(monkeypatch, *events: dict):
    monkeypatch.setenv("OPENAI_API_KEY", f"test-{uuid.uuid4()}")
    body = _responses_sse(*events)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = ChatOpenAI(
        model="muse-spark-1.2-contributor",
        base_url="https://provider.invalid/v1",
        use_responses_api=True,
        http_async_client=client,
    )
    return llm, client


@pytest.mark.parametrize(
    "model",
    ["muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.2-contributor"],
)
def test_provider_family_recognizes_known_muse_ids(model):
    assert isinstance(providers.resolve(_config(model)), MuseSparkProvider)


def test_local_stress_percentile_handles_empty_latency_after_all_errors():
    from scripts.stress_muse_provider import _percentile

    assert _percentile([], 0.95) is None


@pytest.mark.parametrize(
    "model", ["muse-glimmer-30b", "llama-4", "gpt-5.6-luna", "hy3"]
)
def test_does_not_steal_other_families(model):
    assert not isinstance(providers.resolve(_config(model)), MuseSparkProvider)


def test_hy3_uses_dedicated_provider_without_changing_chat_transport():
    provider = providers.resolve(_config("hy3"))
    assert isinstance(provider, Hy3Provider)
    assert provider.transport_candidates(_config("hy3")) == ("openai_chat",)


def test_opencode_go_public_muse_snapshot_is_not_provider_recognition():
    """Official /models availability is narrower than family recognition."""
    assert _GO_PUBLIC_MUSE_MODELS_AS_OF_2026_08_24 == {
        "muse-spark-1.2-contributor"
    }
    assert "muse-spark-1.1" not in _GO_PUBLIC_MUSE_MODELS_AS_OF_2026_08_24
    assert "muse-spark-1.2" not in _GO_PUBLIC_MUSE_MODELS_AS_OF_2026_08_24


@pytest.mark.parametrize(
    "model", ["muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.2-contributor"]
)
def test_known_capabilities(model):
    provider = providers.resolve(_config(model))
    caps = provider.capabilities(_config(model))
    assert caps.provider == "muse_spark"
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window
    assert caps.compaction_threshold == DEFAULT_CAPABILITIES.compaction_threshold
    assert caps.max_output_tokens is None
    assert caps.supports_function_calling is True
    assert caps.supports_reasoning is True
    assert caps.supports_vision is False
    assert caps.cache_breakpoints == ()
    assert caps.effort_options == ()
    assert caps.supports_prompt_cache is (
        model == "muse-spark-1.2-contributor"
    )


def test_unknown_future_model_keeps_conservative_numeric_limits():
    cfg = _config("muse-spark-9.9-experimental")
    caps = providers.resolve(cfg).capabilities(cfg)
    assert caps.provider == "muse_spark"
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window
    assert caps.compaction_threshold == DEFAULT_CAPABILITIES.compaction_threshold
    assert caps.max_output_tokens is None
    assert caps.pricing.input_per_mtok is None


def test_user_capability_override_wins():
    cfg = _config(context_window=64_000)
    caps = providers.resolve(cfg).capabilities(cfg)
    assert caps.context_window == 64_000


@pytest.mark.parametrize(
    "effort",
    [None, "none", "fast", "balanced", "low", "medium", "high", "deep", "xhigh"],
)
def test_opencode_go_does_not_send_unverified_muse_effort(effort):
    cfg = _config()
    if effort is not None:
        cfg["effort"] = effort
    provider = providers.resolve(cfg)
    kwargs = provider.llm_kwargs(cfg, provider.capabilities(cfg))
    assert "reasoning_effort" not in kwargs
    assert "thinking" not in (kwargs.get("extra_body") or {})


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("muse-spark-1.1", False),
        ("muse-spark-1.2", False),
        ("muse-spark-1.2-contributor", True),
    ],
)
def test_only_contributor_selects_responses_on_opencode_go(model, expected):
    provider = MuseSparkProvider()
    assert provider.uses_responses_api(_config(model)) is expected


def test_direct_meta_route_does_not_force_responses():
    provider = MuseSparkProvider()
    go_cfg = _config()
    direct_cfg = {**go_cfg, "base_url": "https://api.meta.ai/v1"}
    assert provider.uses_responses_api(direct_cfg) is False
    assert "use_responses_api" not in provider.llm_kwargs(
        direct_cfg, provider.capabilities(direct_cfg)
    )


def test_temperature_implicit_default_is_omitted_but_explicit_values_survive():
    provider = MuseSparkProvider()
    implicit = _config(temperature=0.7)
    explicit_same = _config(temperature=0.7, temperature_explicit=True)
    explicit_other = _config(temperature=1.0)
    body_value = _config(extra_body={"temperature": 0.9, "safe_flag": True})

    assert "temperature" not in provider.llm_kwargs(
        implicit, provider.capabilities(implicit)
    )
    assert provider.llm_kwargs(
        explicit_same, provider.capabilities(explicit_same)
    )["temperature"] == 0.7
    assert provider.llm_kwargs(
        explicit_other, provider.capabilities(explicit_other)
    )["temperature"] == 1.0
    kwargs = provider.llm_kwargs(body_value, provider.capabilities(body_value))
    assert kwargs["temperature"] == 0.9
    assert kwargs["extra_body"] == {"safe_flag": True}


def test_usage_extracts_responses_and_chat_cache_shapes():
    provider = MuseSparkProvider()
    caps = provider.capabilities(_config())
    assert provider.extract_cache_read(
        {"input_tokens_details": {"cached_tokens": 80}}, caps
    ) == 80
    assert provider.extract_cache_read(
        {"prompt_tokens_details": {"cached_tokens": 40}}, caps
    ) == 40


def test_tool_name_limit_is_checked_without_silent_truncation():
    provider = MuseSparkProvider()
    provider.validate_tool_payloads(
        [{"type": "function", "function": {"name": "x" * 64}}]
    )
    with pytest.raises(ValueError, match=r"tools\[0\] has 65 characters"):
        provider.validate_tool_payloads(
            [{"type": "function", "function": {"name": "x" * 65}}]
        )


def test_langgraph_bind_tools_checks_muse_limit_before_binding():
    class MustNotBind:
        def bind_tools(self, tools, **kwargs):
            pytest.fail("underlying LLM must not bind an invalid Muse tool")

    provider = MuseSparkProvider()
    wrapper = UsageTrackingLLM(
        MustNotBind(),
        provider=provider,
        capabilities=provider.capabilities(_config()),
    )
    tool = {
        "type": "function",
        "function": {
            "name": "x" * 65,
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    with pytest.raises(ValueError, match="at most 64 characters"):
        wrapper.bind_tools([tool])


@pytest.mark.asyncio
async def test_responses_chunk_adapter_preserves_text_tools_and_usage():
    async def source():
        yield SimpleNamespace(
            content=[{"type": "text", "text": "OK", "index": 0}],
            tool_call_chunks=[
                {"index": 1, "id": "call_1", "name": "read", "args": "{\"p\":"}
            ],
            usage_metadata=None,
            chunk_position=None,
        )
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[
                {"index": 1, "id": None, "name": None, "args": "\"x\"}"}
            ],
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "input_token_details": {"cache_read": 75},
                "output_token_details": {"reasoning": 7},
            },
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    chunks = [
        chunk async for chunk in AgentV2._responses_stream_as_chat_chunks(source())
    ]
    assert chunks[0].choices[0].delta.content == "OK"
    assert chunks[0].choices[0].delta.tool_calls[0].function.name == "read"
    assert chunks[1].choices[0].delta.tool_calls[0].function.arguments == "\"x\"}"
    assert chunks[1].usage.prompt_tokens == 100
    assert chunks[1].usage.prompt_tokens_details.cached_tokens == 75
    assert chunks[1]._rxy_responses_terminal is True


@pytest.mark.asyncio
async def test_responses_refusal_is_visible_and_marks_content_filter():
    async def source():
        # Refusal and terminal status may arrive in different public chunks.
        yield SimpleNamespace(
            content=[{"type": "refusal", "refusal": "Not allowed"}],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position=None,
            response_metadata={"status": "in_progress"},
        )
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    chunks = [
        chunk async for chunk in AgentV2._responses_stream_as_chat_chunks(source())
    ]
    assert chunks[0].choices[0].delta.content == "Not allowed"
    assert chunks[-1].choices[0].finish_reason == "content_filter"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_event", ["error", "response.failed"])
async def test_real_langchain_failure_stream_never_becomes_success(
    monkeypatch, failure_event
):
    """Current LangChain drops both failure events and emits a synthetic last chunk."""
    created = {
        "type": "response.created",
        "sequence_number": 0,
        "response": _responses_base("in_progress"),
    }
    if failure_event == "error":
        failed = {
            "type": "error",
            "sequence_number": 1,
            "code": "server_error",
            "message": "provider failed",
            "param": None,
        }
    else:
        failed = {
            "type": "response.failed",
            "sequence_number": 1,
            "response": _responses_base(
                "failed",
                error={"code": "server_error", "message": "provider failed"},
            ),
        }

    llm, client = _mock_responses_llm(monkeypatch, created, failed)
    try:
        with pytest.raises(RuntimeError, match="valid terminal response status"):
            _ = [
                chunk
                async for chunk in AgentV2._responses_stream_as_chat_chunks(
                    llm.astream([HumanMessage(content="test")])
                )
            ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incomplete_reason", "finish_reason"),
    [("max_output_tokens", "length"), ("content_filter", "content_filter")],
)
async def test_real_langchain_incomplete_maps_to_non_success_finish_reason(
    monkeypatch, incomplete_reason, finish_reason
):
    created = {
        "type": "response.created",
        "sequence_number": 0,
        "response": _responses_base("in_progress"),
    }
    output = [
        {
            "id": "msg_test",
            "content": [
                {"annotations": [], "text": "partial", "type": "output_text"}
            ],
            "role": "assistant",
            "status": "incomplete",
            "type": "message",
        }
    ]
    usage = {
        "input_tokens": 1,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 1,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 2,
    }
    incomplete = {
        "type": "response.incomplete",
        "sequence_number": 1,
        "response": _responses_base(
            "incomplete",
            output=output,
            usage=usage,
            incomplete_details={"reason": incomplete_reason},
        ),
    }

    llm, client = _mock_responses_llm(monkeypatch, created, incomplete)
    try:
        chunks = [
            chunk
            async for chunk in AgentV2._responses_stream_as_chat_chunks(
                llm.astream([HumanMessage(content="test")])
            )
        ]
    finally:
        await client.aclose()

    assert chunks[-1].choices[0].finish_reason == finish_reason
    assert chunks[-1]._rxy_responses_terminal is True


@pytest.mark.asyncio
async def test_real_langchain_stream_without_legal_terminal_fails(monkeypatch):
    created = {
        "type": "response.created",
        "sequence_number": 0,
        "response": _responses_base("in_progress"),
    }
    delta = {
        "type": "response.output_text.delta",
        "sequence_number": 1,
        "item_id": "msg_test",
        "output_index": 0,
        "content_index": 0,
        "delta": "partial",
        "logprobs": [],
    }

    llm, client = _mock_responses_llm(monkeypatch, created, delta)
    try:
        with pytest.raises(RuntimeError, match="valid terminal response status"):
            _ = [
                chunk
                async for chunk in AgentV2._responses_stream_as_chat_chunks(
                    llm.astream([HumanMessage(content="test")])
                )
            ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_adapter_tolerates_incomplete_go_sse_with_standalone_deltas():
    """Go may omit item scaffolding; real LangChain deltas must still survive."""
    events = [
        ResponseTextDeltaEvent(
            content_index=0,
            delta="OK",
            item_id="msg_1",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        ),
        ResponseReasoningSummaryTextDeltaEvent(
            delta="brief",
            item_id="reason_1",
            output_index=1,
            sequence_number=2,
            summary_index=0,
            type="response.reasoning_summary_text.delta",
        ),
        ResponseOutputItemAddedEvent(
            item=ResponseFunctionToolCall(
                arguments="",
                call_id="call_1",
                name="read",
                type="function_call",
                id="fc_1",
                status="in_progress",
            ),
            output_index=2,
            sequence_number=3,
            type="response.output_item.added",
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            delta='{"p":"x"}',
            item_id="fc_1",
            output_index=2,
            sequence_number=4,
            type="response.function_call_arguments.delta",
        ),
    ]

    async def parsed_chunks():
        index = output_index = sub_index = 0
        for event in events:
            index, output_index, sub_index, generation = (
                _convert_responses_chunk_to_generation_chunk(
                    event,
                    index,
                    output_index,
                    sub_index,
                )
            )
            if generation is not None:
                yield generation.message
        yield SimpleNamespace(
            content=[],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position="last",
            response_metadata={"status": "completed"},
        )

    chunks = [
        chunk
        async for chunk in AgentV2._responses_stream_as_chat_chunks(parsed_chunks())
    ]
    assert chunks[0].choices[0].delta.content == "OK"
    assert chunks[1].choices[0].delta.reasoning_content == "brief"
    assert chunks[2].choices[0].delta.tool_calls[0].function.name == "read"
    assert chunks[3].choices[0].delta.tool_calls[0].function.arguments == '{"p":"x"}'


@pytest.mark.asyncio
async def test_raw_stream_rejects_overlong_muse_tool_before_sdk(monkeypatch):
    from core import agent_v2

    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )

    class MustNotRun:
        async def astream(self, messages, **kwargs):
            pytest.fail("SDK stream must not open for an invalid Muse tool name")
            yield  # pragma: no cover

    cfg = _config(timeout=5.0)
    provider = MuseSparkProvider()
    agent = object.__new__(AgentV2)
    agent._session_id = "muse-tool-limit-test"
    agent.model_config = cfg
    agent._provider = provider
    agent._capabilities = provider.capabilities(cfg)
    agent._llm = SimpleNamespace(_llm=MustNotRun())
    agent._rate_limiter = None
    agent._thinking_disabled_this_turn = False
    agent._openai_client = lambda: pytest.fail("chat client must not be used")
    tool = SimpleNamespace(name="x" * 65, description="", args={})

    with pytest.raises(ValueError, match="at most 64 characters"):
        _ = [
            chunk
            async for chunk in agent._raw_stream(
                [HumanMessage(content="hi")], tools=[tool], max_tokens=1
            )
        ]


@pytest.mark.asyncio
async def test_raw_stream_uses_langchain_responses_without_unverified_effort(monkeypatch):
    from core import agent_v2

    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )
    captured = {}

    class RawResponsesLLM:
        async def astream(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            yield SimpleNamespace(
                content=[{"type": "text", "text": "READY", "index": 0}],
                tool_call_chunks=[],
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 1,
                    "input_token_details": {"cache_read": 0},
                    "output_token_details": {"reasoning": 0},
                },
                chunk_position="last",
                response_metadata={"status": "completed"},
            )

    cfg = _config(timeout=5.0, effort="high")
    provider = MuseSparkProvider()
    agent = object.__new__(AgentV2)
    agent._session_id = "muse-test"
    agent.model_config = cfg
    agent._provider = provider
    agent._capabilities = provider.capabilities(cfg)
    agent._llm = SimpleNamespace(_llm=RawResponsesLLM())
    agent._rate_limiter = None
    agent._thinking_disabled_this_turn = True
    agent._openai_client = lambda: pytest.fail("chat client must not be used")

    chunks = [
        chunk
        async for chunk in agent._raw_stream(
            [HumanMessage(content="hi")], max_tokens=1
        )
    ]
    assert chunks[0].choices[0].delta.content == "READY"
    assert "reasoning_effort" not in captured["kwargs"]
    assert captured["kwargs"]["max_tokens"] == 1


@pytest.mark.asyncio
async def test_real_chatopenai_builds_responses_wire_payload_without_network(
    monkeypatch,
):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        # The request is intentionally rejected after capture; this test owns
        # SDK request construction, not provider availability.
        return httpx.Response(
            400,
            json={"error": {"message": "captured", "type": "test_error"}},
        )

    async_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("OPENAI_API_KEY", f"test-{uuid.uuid4()}")
    cfg = _config(effort="balanced", temperature=0.7)
    provider = MuseSparkProvider()
    kwargs = provider.llm_kwargs(cfg, provider.capabilities(cfg))
    kwargs["http_async_client"] = async_http
    llm = ChatOpenAI(**kwargs)
    try:
        with pytest.raises(Exception, match="captured"):
            async for _ in llm.astream([HumanMessage(content="hi")]):
                pass
    finally:
        await async_http.aclose()

    assert captured["url"].endswith("/zen/go/v1/responses")
    body = captured["body"]
    assert "input" in body
    assert "messages" not in body
    assert body["max_output_tokens"] == 8192
    assert "reasoning" not in body
    assert "temperature" not in body


@pytest.mark.asyncio
async def test_hy3_keeps_openai_compatible_chat_wire_without_direct_fields(
    monkeypatch,
):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            400,
            json={"error": {"message": "captured", "type": "test_error"}},
        )

    monkeypatch.setenv("OPENAI_API_KEY", f"test-{uuid.uuid4()}")
    async_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = _config("hy3")
    provider = providers.resolve(cfg)
    assert isinstance(provider, Hy3Provider)
    assert provider.uses_responses_api(cfg) is False
    client = AsyncOpenAI(base_url=_GO, http_client=async_http)
    try:
        with pytest.raises(Exception, match="captured"):
            await client.chat.completions.create(
                model="hy3",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=8192,
                stream=True,
            )
    finally:
        await client.close()

    assert captured["url"].endswith("/zen/go/v1/chat/completions")
    body = captured["body"]
    assert "messages" in body
    assert body["max_tokens"] == 8192
    assert "input" not in body
    assert "max_output_tokens" not in body
    wire = json.dumps(body, sort_keys=True)
    for forbidden in (
        "thinking",
        "reasoning_effort",
        "reasoning_content",
        "mandatory_echo",
        "previous_response_id",
    ):
        assert forbidden not in wire
