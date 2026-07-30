"""Lock in the async-LLM-client fix: the streaming path must never fall back
to a blocking synchronous OpenAI client (which would freeze the uvicorn event
loop and stall the SSE stream during LLM generation).

These tests verify *behavior*, not just type names. The contract is:
``_openai_client()`` returns an object whose ``create`` is an **async**
(call it -> awaitable / async iterator) -- whether it is the openai
``AsyncOpenAI`` client or the langchain ``ChatOpenAI.async_client``
(an ``AsyncCompletions`` resource in this SDK version). A blocking sync
client would expose a *synchronous* ``create`` (sync stream), which is
exactly what we must never ship.
"""
import sys
import os
import asyncio

import pytest

# Make the package importable when run from the repo root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from langchain_openai import ChatOpenAI  # noqa: E402
from RxyCode.RxyCode1_1_0.core.agent_v2 import (  # noqa: E402
    AgentV2,
    UsageTrackingLLM,
)


class _FakeLLM:
    """Minimal stand-in: no async_client, so _openai_client must build one."""
    client = None  # sync client would be here if present
    async_client = None  # force the fallback branch


def _make_agent(llm, model_config):
    agent = object.__new__(AgentV2)
    agent._llm = llm
    agent.model_config = model_config
    return agent


def _assert_async_create(client):
    """The client must expose an async (coroutine) create().

    AsyncOpenAI -> client.chat.completions.create (returns a coroutine).
    ChatOpenAI.async_client (AsyncCompletions) -> client.create directly
    (a sync wrapper that returns the coroutine). Either way,
    calling ``create(...)`` must yield an awaitable / async iterator,
    never a *synchronous* blocking stream.

    We actually CALL create (no network: building the coroutine /
    stream object does not hit the wire until it is awaited) and inspect
    the return shape. The coroutine is cancelled via ``.close()`` so
    no request is sent and no "coroutine never awaited" warning fires.
    """
    create = getattr(client, "create", None)
    if create is None:
        create = client.chat.completions.create
    resp = create(model="x", messages=[], stream=True)
    try:
        assert asyncio.iscoroutine(resp) or hasattr(resp, "__aiter__"), (
            "client.create must return an awaitable / async stream; a "
            "blocking sync stream would freeze the event loop during "
            "LLM generation"
        )
    finally:
        if asyncio.iscoroutine(resp):
            resp.close()  # cancel without running network I/O


TEST_API_KEY = "sk-" + "test-" + "0123456789abcdef" * 2


def test_openai_client_fallback_is_async():
    agent = _make_agent(
        _FakeLLM(),
        {"api_key": TEST_API_KEY,
         "base_url": "https://api.example.com/v1"},
    )
    client = agent._openai_client()
    # Fallback must build a real async client (AsyncOpenAI), carrying
    # the configured endpoint.
    assert str(client.base_url).rstrip("/") == "https://api.example.com/v1"
    _assert_async_create(client)


def test_openai_client_prefers_existing_async_client():
    """The existing async_client (prod type) is returned as-is."""
    chat = ChatOpenAI(
        model="gpt-4o",
        api_key=TEST_API_KEY,
        base_url="https://api.example.com/v1",
    )
    existing = chat.async_client  # real production type (AsyncCompletions)
    llm = _FakeLLM()
    llm.async_client = existing
    agent = _make_agent(
        llm, {"api_key": "x", "base_url": "https://api.example.com/v1"},
    )
    returned = agent._openai_client()
    assert returned is existing
    _assert_async_create(returned)


def test_openai_client_real_production_path():
    """Cover the real UsageTrackingLLM -> ChatOpenAI.async_client forward.

    ``UsageTrackingLLM.__getattr__`` forwards unknown attributes to
    the inner ``ChatOpenAI``, so ``getattr(llm, "async_client", None)``
    must reach the inner client's lazily-built async client. This is the
    path the previous fake-only test never exercised.
    """
    chat = ChatOpenAI(
        model="gpt-4o",
        api_key=TEST_API_KEY,
        base_url="https://api.example.com/v1",
    )
    agent = _make_agent(
        UsageTrackingLLM(llm=chat),
        {"api_key": TEST_API_KEY,
         "base_url": "https://api.example.com/v1"},
    )
    client = agent._openai_client()
    _assert_async_create(client)


def test_openai_client_fallback_handles_empty_base_url():
    """An empty base_url must not raise; the SDK default host applies."""
    agent = _make_agent(
        _FakeLLM(),
        {"api_key": TEST_API_KEY,
         "base_url": None},
    )
    client = agent._openai_client()
    _assert_async_create(client)
    assert str(client.base_url).startswith("https://")
