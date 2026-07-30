from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


class FakeMemory:
    def __init__(self, context: str = ""):
        self.context = context

    async def initialize(self):
        return None

    def load_session(self):
        return None

    def get_context_for_prompt(self):
        return self.context

    def add_interaction(self, *_args):
        return None

    def save_session(self):
        return None


class Chunk:
    def __init__(self, content: str):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(
            content=content,
            reasoning_content="",
            tool_calls=None,
        ))]
        self.usage = None


class UsageChunk:
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5):
        self.choices = []
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )


class ToolCallChunk:
    def __init__(self, name: str = "read"):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(
            content="",
            reasoning_content="",
            tool_calls=[SimpleNamespace(
                index=0,
                id="call-1",
                function=SimpleNamespace(name=name, arguments='{"path":"file.txt"}'),
            )],
        ))]
        self.usage = None


def make_agent(
    search_result: str,
    answer: str = "Verified answer https://example.com/source",
    memory_context: str = "",
    fetch_results: dict[str, str | BaseException] | None = None,
):
    agent = object.__new__(AgentV2)
    agent._session_loaded = True
    agent._session_id = "test-session"
    agent._memory = FakeMemory(memory_context)
    agent._llm = None
    agent._tool_orchestrator = None
    agent.model_config = {
        "base_url": "https://api.example.test/v1",
        "model_name": "test-model",
    }
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []
    async def execute_tool(name, args, **_kwargs):
        if name == "websearch":
            return search_result
        if name == "webfetch":
            if fetch_results is not None:
                result = fetch_results.get(
                    args["url"], "[error fetching source: no fixture]"
                )
                if isinstance(result, BaseException):
                    raise result
                return result
            return "Verified source content from the fetched page."
        return f"[error: unexpected tool {name}]"

    agent._execute_tool = AsyncMock(side_effect=execute_tool)
    agent._get_core_tools = MagicMock(return_value=[])
    captured_messages = []

    async def raw_stream(messages, _tools=None):
        captured_messages.extend(messages)
        yield Chunk(answer)

    agent._raw_stream = raw_stream
    agent._maybe_compress_context = AsyncMock()
    return agent, captured_messages


@pytest.mark.asyncio
async def test_fresh_query_ignores_cached_answer_and_stops_when_search_unverified(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache

    precise_get = MagicMock(return_value={"response": "stale precise answer"})
    semantic_get = MagicMock(return_value={"response": "stale semantic answer"})
    monkeypatch.setattr(precise_cache, "get", precise_get)
    monkeypatch.setattr(semantic_cache, "get", semantic_get)
    agent, captured = make_agent("[error: all search engines failed]")

    result = await agent._fast_reply_with_tools("今天最新 Python 版本是什么？")

    precise_get.assert_not_called()
    semantic_get.assert_not_called()
    agent._execute_tool.assert_awaited_once_with(
        "websearch",
        {"query": "今天最新 Python 版本是什么？", "numResults": 5},
        call_id="required_web_research",
    )
    assert captured == []
    assert "will not guess" in result


@pytest.mark.asyncio
async def test_fresh_query_fails_honestly_when_search_tool_raises():
    agent, captured = make_agent("unused")
    agent._execute_tool = AsyncMock(side_effect=RuntimeError("network unavailable"))

    result = await agent._fast_reply_with_tools("Search for the Python release")

    assert "could not verify" in result
    assert "web search execution failed" in result
    assert captured == []


@pytest.mark.asyncio
async def test_verified_fresh_query_injects_sources_and_does_not_cache(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache

    precise_put = MagicMock()
    semantic_put = MagicMock()
    monkeypatch.setattr(precise_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(semantic_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(precise_cache, "put", precise_put)
    monkeypatch.setattr(semantic_cache, "put", semantic_put)
    search = "Python release\n  https://example.com/source\n  Current stable release details"
    agent, captured = make_agent(search, answer="The verified stable release is available now.")

    result = await agent._fast_reply_with_tools("What is the current Python version?")

    assert "Sources:" in result
    assert "https://example.com/source" in result
    assert agent._execute_tool.await_args_list == [
        call(
            "websearch",
            {
                "query": "What is the current Python version?",
                "numResults": 5,
            },
            call_id="required_web_research",
        ),
        call(
            "webfetch",
            {
                "url": "https://example.com/source",
                "format": "text",
                "timeout": 30,
            },
            call_id="required_web_fetch_0",
        ),
    ]
    assert any(
        "Verified source content" in str(getattr(message, "content", ""))
        for message in captured
    )
    precise_put.assert_not_called()
    semantic_put.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_query_fails_honestly_when_no_search_result_can_be_fetched():
    search = (
        "First\n  https://one.example/source\n  result\n\n"
        "Second\n  https://two.example/source\n  result"
    )
    agent, captured = make_agent(
        search,
        fetch_results={
            "https://one.example/source": "[error fetching source: timeout]",
            "https://two.example/source": "[blocked: network policy]",
        },
    )

    result = await agent._fast_reply_with_tools("What is the weather in Shanghai?")

    assert "could not verify" in result
    assert "will not guess" in result
    assert "none could be fetched" in result
    assert captured == []


@pytest.mark.asyncio
async def test_fresh_query_handles_fetch_exceptions_and_tries_next_candidate():
    search = (
        "Broken\n  https://broken.example/source\n  result\n\n"
        "Working\n  https://working.example/source\n  result"
    )
    agent, _captured = make_agent(
        search,
        answer="Answer based on the working source.",
        fetch_results={
            "https://broken.example/source": RuntimeError("network failed"),
            "https://working.example/source": "Successfully fetched evidence",
        },
    )

    result = await agent._fast_reply_with_tools("Search for the release details")

    assert "https://working.example/source" in result
    assert "https://broken.example/source" not in result


@pytest.mark.asyncio
async def test_required_research_only_exposes_and_cites_successfully_fetched_urls():
    search = (
        "Unreachable\n  https://bad.example/source\n  stale snippet\n\n"
        "Official\n  https://good.example/source\n  current snippet"
    )
    agent, captured = make_agent(
        search,
        answer="The fetched source supports the answer.",
        fetch_results={
            "https://bad.example/source": "[error fetching source: timeout]",
            "https://good.example/source": "Authoritative fetched details",
        },
    )

    result = await agent._fast_reply_with_tools("Search the web for this release")

    assert "https://good.example/source" in result
    assert "https://bad.example/source" not in result
    prompt_text = "\n".join(str(getattr(message, "content", "")) for message in captured)
    assert "Authoritative fetched details" in prompt_text
    assert "stale snippet" not in prompt_text
    assert "https://bad.example/source" not in prompt_text


@pytest.mark.asyncio
async def test_required_research_rejects_unfetched_model_citation():
    search = "Official\n  https://good.example/source\n  current snippet"
    agent, _captured = make_agent(
        search,
        answer="Claim from https://unverified.example/source",
        fetch_results={
            "https://good.example/source": "Authoritative fetched details",
        },
    )

    result = await agent._fast_reply_with_tools("Browse the web for this release")

    assert "could not verify" in result
    assert "not successfully fetched" in result
    assert "https://unverified.example/source" not in result


@pytest.mark.asyncio
async def test_tool_aware_fast_path_bypasses_application_answer_caches(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    precise_get = MagicMock(return_value={"response": "polluted precise answer"})
    semantic_get = MagicMock(return_value={"response": "polluted semantic answer"})
    precise_put = MagicMock()
    semantic_put = MagicMock()
    record_cache = MagicMock()
    monkeypatch.setattr(precise_cache, "get", precise_get)
    monkeypatch.setattr(semantic_cache, "get", semantic_get)
    monkeypatch.setattr(precise_cache, "put", precise_put)
    monkeypatch.setattr(semantic_cache, "put", semantic_put)
    monkeypatch.setattr(token_stats, "record_application_cache", record_cache)
    agent, _captured = make_agent("unused", answer="fresh uncached answer")

    result = await agent._fast_reply_with_tools("Summarize merge sort")

    assert result == "fresh uncached answer"
    precise_get.assert_not_called()
    semantic_get.assert_not_called()
    precise_put.assert_not_called()
    semantic_put.assert_not_called()
    assert record_cache.call_args_list == [
        (("precise",), {"bypass": True}),
        (("semantic",), {"bypass": True}),
    ]


@pytest.mark.asyncio
async def test_raw_stream_requests_usage_chunks():
    captured = {}

    async def stream():
        if False:
            yield None

    def create(**payload):
        captured.update(payload)
        return stream()

    agent, _captured = make_agent("unused")
    agent._openai_client = MagicMock(return_value=SimpleNamespace(create=create))
    agent._llm = SimpleNamespace()

    chunks = [chunk async for chunk in AgentV2._raw_stream(agent, [])]

    assert chunks == []
    assert captured["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_tool_free_fast_path_does_not_estimate_after_real_usage(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    monkeypatch.setattr(precise_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(semantic_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(precise_cache, "put", MagicMock())
    monkeypatch.setattr(semantic_cache, "put", MagicMock())
    add_usage = MagicMock()
    monkeypatch.setattr(token_stats, "add_real_usage", add_usage)
    agent, _captured = make_agent("unused", answer="generated answer")

    async def raw_stream(messages, _tools=None):
        yield Chunk("generated answer")
        yield UsageChunk(10, 5)

    agent._raw_stream = raw_stream

    result = await agent._fast_reply("Summarize merge sort")

    assert result == "generated answer"
    add_usage.assert_called_once_with(10, 5, 0)


@pytest.mark.asyncio
async def test_tool_aware_fast_path_does_not_estimate_after_real_usage(monkeypatch):
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    add_usage = MagicMock()
    monkeypatch.setattr(token_stats, "add_real_usage", add_usage)
    agent, _captured = make_agent("unused", answer="generated answer")

    async def raw_stream(messages, _tools=None):
        yield Chunk("generated answer")
        yield UsageChunk(10, 5)

    agent._raw_stream = raw_stream

    result = await agent._fast_reply_with_tools("Summarize merge sort")

    assert result == "generated answer"
    add_usage.assert_called_once_with(10, 5, 0)


@pytest.mark.asyncio
async def test_tool_free_fast_path_estimates_after_empty_usage(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    monkeypatch.setattr(precise_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(semantic_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(precise_cache, "put", MagicMock())
    monkeypatch.setattr(semantic_cache, "put", MagicMock())
    add_usage = MagicMock()
    monkeypatch.setattr(token_stats, "add_real_usage", add_usage)
    agent, _captured = make_agent("unused", answer="generated answer")

    async def raw_stream(messages, _tools=None):
        yield Chunk("generated answer")
        yield UsageChunk(0, 0)

    agent._raw_stream = raw_stream

    result = await agent._fast_reply("Summarize merge sort")

    assert result == "generated answer"
    add_usage.assert_called_once()
    assert add_usage.call_args.args != (0, 0, 0)


@pytest.mark.asyncio
async def test_tool_aware_fast_path_estimates_each_round_missing_usage(monkeypatch):
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    add_usage = MagicMock()
    monkeypatch.setattr(token_stats, "add_real_usage", add_usage)
    agent, _captured = make_agent("unused")
    agent._execute_tool = AsyncMock(return_value="file contents")
    calls = 0

    async def raw_stream(messages, _tools=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallChunk()
            yield UsageChunk(10, 5)
        else:
            yield Chunk("final answer")

    agent._raw_stream = raw_stream

    result = await agent._fast_reply_with_tools("Read file.txt")

    assert result == "final answer"
    assert add_usage.call_count == 2
    assert add_usage.call_args_list[0].args == (10, 5, 0)
    assert add_usage.call_args_list[1].args != (0, 0, 0)


def test_application_cache_namespace_isolates_api_keys():
    agent_a, _captured = make_agent("unused")
    agent_b, _captured = make_agent("unused")
    agent_a.model_config["api_key"] = "tenant-a-secret"
    agent_b.model_config["api_key"] = "tenant-b-secret"

    namespace_a = agent_a._application_cache_namespace()
    namespace_b = agent_b._application_cache_namespace()

    assert namespace_a != namespace_b
    assert "tenant-a-secret" not in namespace_a
    assert "tenant-b-secret" not in namespace_b


@pytest.mark.asyncio
async def test_tool_free_fast_path_namespaces_and_records_precise_cache_hit(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    precise_get = MagicMock(return_value={"response": "cached answer"})
    semantic_get = MagicMock()
    record_cache = MagicMock()
    monkeypatch.setattr(precise_cache, "get", precise_get)
    monkeypatch.setattr(semantic_cache, "get", semantic_get)
    monkeypatch.setattr(token_stats, "record_application_cache", record_cache)
    agent, _captured = make_agent("unused")

    result = await agent._fast_reply("Summarize merge sort")

    assert result == "cached answer"
    namespace = agent._application_cache_namespace()
    assert precise_get.call_args.kwargs["namespace"] == namespace
    assert record_cache.call_args_list == [
        (("precise",), {"hit": True}),
        (("semantic",), {"bypass": True}),
    ]
    semantic_get.assert_not_called()


@pytest.mark.asyncio
async def test_tool_free_fast_path_namespaces_and_records_semantic_cache_hit(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    precise_get = MagicMock(return_value=None)
    semantic_get = MagicMock(return_value={"response": "semantic answer"})
    record_cache = MagicMock()
    monkeypatch.setattr(precise_cache, "get", precise_get)
    monkeypatch.setattr(semantic_cache, "get", semantic_get)
    monkeypatch.setattr(token_stats, "record_application_cache", record_cache)
    agent, _captured = make_agent("unused")

    result = await agent._fast_reply("Summarize merge sort")

    assert result == "semantic answer"
    namespace = agent._application_cache_namespace()
    assert precise_get.call_args.kwargs["namespace"] == namespace
    assert semantic_get.call_args.kwargs["namespace"] == namespace
    assert record_cache.call_args_list == [
        (("precise",), {"hit": False}),
        (("semantic",), {"hit": True}),
    ]


@pytest.mark.asyncio
async def test_tool_free_fast_path_namespaces_cache_writes_after_misses(monkeypatch):
    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    precise_put = MagicMock()
    semantic_put = MagicMock()
    record_cache = MagicMock()
    monkeypatch.setattr(precise_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(semantic_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(precise_cache, "put", precise_put)
    monkeypatch.setattr(semantic_cache, "put", semantic_put)
    monkeypatch.setattr(token_stats, "record_application_cache", record_cache)
    agent, _captured = make_agent("unused", answer="generated answer")

    result = await agent._fast_reply("Summarize merge sort")

    assert result == "generated answer"
    namespace = agent._application_cache_namespace()
    assert precise_put.call_args.kwargs["namespace"] == namespace
    assert semantic_put.call_args.kwargs["namespace"] == namespace
    assert record_cache.call_args_list == [
        (("precise",), {"hit": False}),
        (("semantic",), {"hit": False}),
    ]


@pytest.mark.asyncio
async def test_tool_free_fast_path_uses_complete_memory_context_in_cache_key(monkeypatch):
    import hashlib
    import json

    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    precise_get = MagicMock(return_value=None)
    monkeypatch.setattr(precise_cache, "get", precise_get)
    monkeypatch.setattr(semantic_cache, "get", MagicMock(return_value=None))
    monkeypatch.setattr(precise_cache, "put", MagicMock())
    record_cache = MagicMock()
    monkeypatch.setattr(token_stats, "record_application_cache", record_cache)
    shared_prefix = "x" * 200
    context_a = shared_prefix + " first ending"
    context_b = shared_prefix + " second ending"

    agent_a, _captured = make_agent("unused", memory_context=context_a)
    await agent_a._fast_reply("Summarize merge sort")
    first_key = precise_get.call_args.args[1]

    agent_b, _captured = make_agent("unused", memory_context=context_b)
    await agent_b._fast_reply("Summarize merge sort")
    second_key = precise_get.call_args.args[1]

    assert first_key != second_key
    assert first_key == json.dumps(
        [
            "Summarize merge sort",
            hashlib.sha256(context_a.encode("utf-8")).hexdigest(),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert record_cache.call_args_list == [
        (("precise",), {"hit": False}),
        (("semantic",), {"bypass": True}),
        (("precise",), {"hit": False}),
        (("semantic",), {"bypass": True}),
    ]


@pytest.mark.asyncio
async def test_tool_path_nonfresh_internal_failure_does_not_use_tool_free_reply():
    agent, _captured = make_agent("unused")
    agent._raw_stream = MagicMock(side_effect=RuntimeError("stream failed"))
    agent._fast_reply = AsyncMock(return_value="unsafe cached fallback")

    with pytest.raises(RuntimeError, match="stream failed"):
        await agent._fast_reply_with_tools("Explain merge sort")

    agent._fast_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_nonfresh_tool_failure_falls_through_without_tool_free_reply():
    agent, _captured = make_agent("unused")
    agent._cancelled = False
    agent._fast_reply_with_tools = AsyncMock(side_effect=RuntimeError("tool path failed"))
    agent._fast_reply = AsyncMock(return_value="unsafe cached fallback")
    agent._is_simple_query = MagicMock(return_value=True)
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._should_use_subagents = MagicMock(return_value=False)
    agent._graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"final_response": "pipeline answer"})
    )

    result = await agent.run("Explain merge sort")

    assert result == "pipeline answer"
    agent._fast_reply.assert_not_awaited()
    agent._graph.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_does_not_fallback_to_tool_free_answer_when_research_fails():
    agent = object.__new__(AgentV2)
    agent._cancelled = False
    agent._memory = SimpleNamespace(
        initialize=AsyncMock(),
        load_session=MagicMock(),
    )
    agent._session_loaded = True
    agent._detect_file_operation = MagicMock(return_value=None)
    agent._detect_download_intent = MagicMock(return_value=None)
    agent._should_use_subagents = MagicMock(return_value=False)
    agent._is_simple_query = MagicMock(return_value=True)
    agent._fast_reply_with_tools = AsyncMock(side_effect=RuntimeError("search unavailable"))
    agent._fast_reply = AsyncMock(return_value="unguarded stale guess")

    result = await agent.run("What is the latest Python release?", mode="build")

    assert "could not verify" in result
    assert "will not guess" in result
    agent._fast_reply.assert_not_awaited()
