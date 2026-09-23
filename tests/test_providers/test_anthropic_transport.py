"""Native Anthropic Messages transport and public-chunk normalization."""

from __future__ import annotations

import json
import os
import builtins
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from config.model_capabilities import DEFAULT_CAPABILITIES
from core import agent_v2
from core.agent_v2 import AgentV2
from core.providers.anthropic import AnthropicProvider


def _config(**extra):
    return {
        "model_name": "claude-haiku-4-5",
        "base_url": "https://api.anthropic.com/v1",
        "resolved_max_tokens": 32,
        "timeout": 5.0,
        **extra,
    }


def _text_sse() -> str:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-haiku-4-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 7,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 2,
                        "output_tokens": 1,
                    },
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "ANTHROPIC_OK"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {
                    "input_tokens": 7,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 2,
                    "output_tokens": 4,
                },
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(
        f"event: {event}\ndata: {json.dumps(data)}\n\n" for event, data in events
    )


def _tool_sse() -> str:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_tool",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-haiku-4-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_test",
                    "name": "read",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"path":"a.py"}',
                },
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"input_tokens": 3, "output_tokens": 8},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(
        f"event: {event}\ndata: {json.dumps(data)}\n\n" for event, data in events
    )


def test_native_anthropic_route_is_messages_only():
    provider = AnthropicProvider()
    assert provider.transport_candidates(_config()) == ("anthropic_messages",)
    assert provider.transport_candidates(
        _config(base_url="https://proxy.example/v1")
    ) == ("openai_chat",)


def test_native_thinking_blocks_are_replayable_with_signatures():
    messages = [
        AIMessage(
            content=[
                {"type": "thinking", "thinking": "plan", "signature": "sig-1"},
                {"type": "redacted_thinking", "data": "opaque"},
                {"type": "text", "text": "calling a tool"},
            ],
            tool_calls=[
                {"name": "read", "args": {"path": "a.py"}, "id": "tool-1"}
            ],
        )
    ]
    replay = AgentV2._to_anthropic_messages(messages)
    assert replay[0].content[0] == {
        "type": "thinking",
        "thinking": "plan",
        "signature": "sig-1",
    }
    assert replay[0].content[1] == {
        "type": "redacted_thinking",
        "data": "opaque",
    }


def test_native_cache_control_is_moved_to_content_block_with_ttl():
    messages = [
        SystemMessage(
            content="stable system",
            additional_kwargs={
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
            },
        ),
        HumanMessage(content="request"),
    ]
    replay = AgentV2._to_anthropic_messages(messages)
    assert replay[0].content == [
        {
            "type": "text",
            "text": "stable system",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


def test_native_tool_cache_control_is_preserved_in_anthropic_shape():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]
    assert AgentV2._to_anthropic_tools(tools) == [
        {
            "name": "read",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}},
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


def test_anthropic_cache_write_usage_is_extracted():
    provider = AnthropicProvider()
    caps = provider.capabilities(_config())
    assert provider.extract_cache_write(
        {"input_token_details": {"cache_creation": 17}}, caps
    ) == 17


def test_anthropic_cache_write_usage_reaches_token_stats(monkeypatch):
    observed = []
    monkeypatch.setattr(
        agent_v2.token_stats,
        "add_real_usage",
        lambda input_tokens, output_tokens, cache_read, cache_write: observed.append(
            (input_tokens, output_tokens, cache_read, cache_write)
        ),
    )
    response = SimpleNamespace(
        usage_metadata={
            "input_tokens": 20,
            "output_tokens": 4,
            "input_token_details": {
                "cache_read": 2,
                "cache_creation": 17,
            },
        },
        response_metadata={},
    )
    provider = AnthropicProvider()
    agent_v2._record_usage(
        response,
        provider=provider,
        caps=provider.capabilities(_config()),
    )
    assert observed == [(20, 4, 2, 17)]


def test_missing_langchain_anthropic_dependency_is_diagnostic(monkeypatch):
    provider = AnthropicProvider()
    monkeypatch.setattr(agent_v2.providers, "resolve", lambda _cfg: provider)
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "langchain_anthropic":
            raise ImportError("dependency intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    agent = object.__new__(AgentV2)
    agent._session_id = "anthropic-dependency-test"
    agent._rate_limiter = None
    agent._rate_limit_timeout = 0.0
    agent._rate_reserved_output_tokens = 0
    credential = "test-" + uuid4().hex

    with pytest.raises(RuntimeError, match="requires langchain-anthropic") as exc_info:
        agent._build_llm_from_config(
            _config(api_key=credential, api_key_env="RXYCODE_TEST_UNUSED_KEY")
        )
    assert credential not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured_url",
    [
        "https://api.anthropic.com/v1",
        "https://api.anthropic.com/v1/messages",
    ],
)
async def test_native_messages_wire_and_agent_normalization(
    monkeypatch, configured_url
):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )
    env_name = "RXYCODE_TEST_ANTHROPIC_KEY"
    monkeypatch.setenv(env_name, "test-" + uuid4().hex)
    observed: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=_text_sse(),
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider()
    cfg = _config(
        base_url=configured_url,
        api_key=os.environ[env_name],
        api_key_env=env_name,
    )
    raw_llm = ChatAnthropic(
        **provider.anthropic_llm_kwargs(cfg, provider.capabilities(cfg))
    )
    raw_llm.__dict__["_async_client"] = AsyncAnthropic(
        api_key=os.environ[env_name],
        base_url=raw_llm.anthropic_api_url,
        http_client=http_client,
    )

    agent = object.__new__(AgentV2)
    agent._session_id = "anthropic-transport-test"
    agent.model_config = _config(base_url=configured_url, api_key_env=env_name)
    agent._provider = provider
    agent._capabilities = provider.capabilities(agent.model_config)
    agent._llm = SimpleNamespace(_llm=raw_llm)
    agent._rate_limiter = None
    agent._thinking_disabled_this_turn = False

    def reject_openai_client():
        raise AssertionError("Anthropic transport must not create an OpenAI client")

    agent._openai_client = reject_openai_client
    messages = [
        SystemMessage(content="system policy"),
        HumanMessage(
            content=[
                {"type": "text", "text": "inspect"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,aQ=="},
                },
            ]
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": "a.py"}, "id": "tc1"}],
        ),
        ToolMessage(content="file text", tool_call_id="tc1"),
        HumanMessage(content="continue"),
    ]
    tool_parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    tools = [
        SimpleNamespace(
            name="read",
            description="Read a file",
            args=tool_parameters["properties"],
        )
    ]
    chunks = [
        chunk
        async for chunk in agent._raw_stream(messages, tools=tools, max_tokens=32)
    ]
    await http_client.aclose()

    assert observed["url"] == "https://api.anthropic.com/v1/messages"
    assert "x-api-key" in observed["headers"]
    assert "anthropic-version" in observed["headers"]
    assert "authorization" not in observed["headers"]
    body = observed["body"]
    assert body["system"] == "system policy"
    assert body["tools"][0]["name"] == "read"
    assert body["tools"][0]["description"] == "Read a file"
    assert body["tools"][0]["input_schema"] == tool_parameters
    assert body["tools"][0]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }
    assert any(
        block.get("type") == "image"
        for message in body["messages"]
        for block in (
            message["content"] if isinstance(message.get("content"), list) else []
        )
        if isinstance(block, dict)
    )
    assert any(
        block.get("type") == "tool_use"
        for message in body["messages"]
        for block in (
            message["content"] if isinstance(message.get("content"), list) else []
        )
        if isinstance(block, dict)
    )
    assert any(
        block.get("type") == "tool_result"
        for message in body["messages"]
        for block in (
            message["content"] if isinstance(message.get("content"), list) else []
        )
        if isinstance(block, dict)
    )
    assert "".join(chunk.choices[0].delta.content for chunk in chunks) == (
        "ANTHROPIC_OK"
    )
    assert chunks[-1].choices[0].finish_reason == "stop"
    # LangChain reports cache-read input in the total as well as the detail.
    assert chunks[-1].usage.prompt_tokens == 9
    assert chunks[-1].usage.completion_tokens == 4
    assert chunks[-1].usage.prompt_tokens_details.cached_tokens == 2
    observed_usage = []
    monkeypatch.setattr(
        agent_v2.token_stats,
        "add_real_usage",
        lambda input_tokens, output_tokens, cache_read: observed_usage.append(
            (input_tokens, output_tokens, cache_read)
        ),
    )
    agent_v2._record_usage(
        chunks[-1], provider=provider, caps=provider.capabilities(agent.model_config)
    )
    assert observed_usage == [(9, 4, 2)]


@pytest.mark.asyncio
async def test_native_messages_tool_stream_is_normalized(monkeypatch):
    env_name = "RXYCODE_TEST_ANTHROPIC_TOOL_KEY"
    monkeypatch.setenv(env_name, "test-" + uuid4().hex)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=_tool_sse(),
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider()
    cfg = _config(api_key=os.environ[env_name], api_key_env=env_name)
    raw_llm = ChatAnthropic(
        **provider.anthropic_llm_kwargs(cfg, provider.capabilities(cfg))
    )
    raw_llm.__dict__["_async_client"] = AsyncAnthropic(
        api_key=os.environ[env_name],
        base_url=raw_llm.anthropic_api_url,
        http_client=http_client,
    )
    bound = raw_llm.bind_tools(
        [
            {
                "name": "read",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]
    )

    chunks = [
        chunk
        async for chunk in AgentV2._anthropic_stream_as_chat_chunks(
            bound.astream([HumanMessage(content="read a.py")], max_tokens=32)
        )
    ]
    await http_client.aclose()

    calls = [call for chunk in chunks for call in chunk.choices[0].delta.tool_calls]
    assert any(call.id == "toolu_test" and call.function.name == "read" for call in calls)
    assert "".join(str(call.function.arguments or "") for call in calls) == (
        '{"path":"a.py"}'
    )
    assert chunks[-1].choices[0].finish_reason == "tool_calls"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_reason", "finish_reason"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("tool_use", "tool_calls"),
        ("max_tokens", "length"),
        ("model_context_window_exceeded", "length"),
        ("refusal", "content_filter"),
    ],
)
async def test_anthropic_terminal_mapping(stop_reason, finish_reason):
    async def public_chunks():
        yield SimpleNamespace(
            content="",
            tool_call_chunks=[],
            usage_metadata=None,
            response_metadata={"stop_reason": stop_reason},
            chunk_position="last",
        )

    chunks = [
        chunk
        async for chunk in AgentV2._anthropic_stream_as_chat_chunks(public_chunks())
    ]
    assert chunks[-1].choices[0].finish_reason == finish_reason


@pytest.mark.asyncio
async def test_anthropic_thinking_blocks_reach_internal_reasoning_field():
    async def public_chunks():
        yield SimpleNamespace(
            content=[{"type": "thinking", "thinking": "plan first"}],
            tool_call_chunks=[],
            usage_metadata=None,
            response_metadata={},
            chunk_position=None,
        )
        yield SimpleNamespace(
            content=[{"type": "text", "text": "answer"}],
            tool_call_chunks=[],
            usage_metadata=None,
            response_metadata={"stop_reason": "end_turn"},
            chunk_position="last",
        )

    chunks = [
        chunk
        async for chunk in AgentV2._anthropic_stream_as_chat_chunks(public_chunks())
    ]
    provider = AnthropicProvider()
    caps = provider.capabilities(_config())
    reasoning = provider.extract_reasoning(
        chunks[0].choices[0].delta, caps
    )
    assert reasoning == "plan first"


@pytest.mark.asyncio
async def test_native_messages_protocol_error_is_diagnostic_without_fallback(
    monkeypatch,
):
    monkeypatch.setattr(
        agent_v2._circuit_breaker, "circuit_breaker_enabled", lambda: False
    )
    env_name = "RXYCODE_TEST_ANTHROPIC_ERROR_KEY"
    monkeypatch.setenv(env_name, "test-" + uuid4().hex)
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            400,
            request=request,
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "invalid anthropic-version header",
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider()
    cfg = _config(api_key=os.environ[env_name], api_key_env=env_name)
    raw_llm = ChatAnthropic(
        **provider.anthropic_llm_kwargs(cfg, provider.capabilities(cfg))
    )
    raw_llm.__dict__["_async_client"] = AsyncAnthropic(
        api_key=os.environ[env_name],
        base_url=raw_llm.anthropic_api_url,
        http_client=http_client,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "anthropic-error-test"
    agent.model_config = _config(api_key_env=env_name)
    agent._provider = provider
    agent._capabilities = provider.capabilities(agent.model_config)
    agent._llm = SimpleNamespace(_llm=raw_llm)
    agent._rate_limiter = None
    agent._thinking_disabled_this_turn = False
    agent._openai_client = lambda: pytest.fail(
        "Anthropic protocol errors must not fall back to an OpenAI client"
    )

    with pytest.raises(Exception, match="anthropic-version") as exc_info:
        _ = [
            chunk
            async for chunk in agent._raw_stream(
                [HumanMessage(content="hi")], max_tokens=32
            )
        ]
    await http_client.aclose()

    assert request_count == 1
    assert os.environ[env_name] not in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_normalizer_rejects_missing_terminal():
    async def public_chunks():
        yield SimpleNamespace(
            content="partial",
            tool_call_chunks=[],
            usage_metadata=None,
            response_metadata={},
            chunk_position=None,
        )

    normalizer = getattr(AgentV2, "_anthropic_stream_as_chat_chunks", None)
    assert callable(normalizer)
    with pytest.raises(RuntimeError, match="terminal"):
        _ = [chunk async for chunk in normalizer(public_chunks())]
