"""Bug C: prompt_prefix_cache must be applied to the system message.

The config flag `cache.prompt_prefix_cache: true` exists but was never
applied to the actual LLM call, so DeepSeek could not cache the system
prompt prefix -> ~60% cache hit rate instead of ~100%, and every call
re-prefilled the (large) system prompt.

These tests verify that UsageTrackingLLM (the single chokepoint for ALL
LLM calls) injects `cache_control` on the first SystemMessage when the
flag is enabled, and leaves messages untouched when disabled.
"""
import sys
import types
import pytest
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

PKG = "RxyCode.RxyCode1_1_0"


class _FakeLLM:
    """Records the messages it receives so we can assert cache_control."""

    def __init__(self):
        self.received = None
        self.calls = 0

    async def ainvoke(self, messages, **kwargs):
        self.received = messages
        self.calls += 1
        return AIMessage(content="ok", additional_kwargs={})

    async def astream(self, messages, **kwargs):
        self.received = messages
        self.calls += 1
        # minimal streaming chunk
        class _Chunk:
            content = "ok"
            additional_kwargs = {}
            reasoning_content = ""
        yield _Chunk()


def _load_cfg(enabled: bool):
    def _fake_load_config():
        return {"cache": {"enabled": True, "prompt_prefix_cache": enabled, "ttl": 3600}}
    return _fake_load_config


def _get_wrapper(monkeypatch, enabled: bool):
    # Patch load_config in the settings module BEFORE importing the wrapper,
    # because UsageTrackingLLM reads config lazily inside ainvoke/astream.
    settings = types.ModuleType(f"{PKG}.config.settings")
    settings.load_config = _load_cfg(enabled)
    monkeypatch.setitem(sys.modules, f"{PKG}.config.settings", settings)

    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    return UsageTrackingLLM(_FakeLLM())


@pytest.mark.asyncio
async def test_cache_control_injected_when_enabled(monkeypatch):
    """Bug C: with prompt_prefix_cache=true, the system message must carry
    cache_control so DeepSeek caches the prefix."""
    wrapper = _get_wrapper(monkeypatch, enabled=True)
    msgs = [SystemMessage(content="SYS_PROMPT"), HumanMessage(content="hi")]
    await wrapper.ainvoke(msgs)

    recv = wrapper._llm.received
    assert isinstance(recv[0], SystemMessage)
    ak = getattr(recv[0], "additional_kwargs", {}) or {}
    assert ak.get("cache_control") == {"type": "ephemeral"}, (
        f"expected cache_control on system message, got {ak}"
    )


@pytest.mark.asyncio
async def test_no_cache_control_when_disabled(monkeypatch):
    """When the flag is off, messages must be passed through unchanged."""
    wrapper = _get_wrapper(monkeypatch, enabled=False)
    msgs = [SystemMessage(content="SYS_PROMPT"), HumanMessage(content="hi")]
    await wrapper.ainvoke(msgs)

    recv = wrapper._llm.received
    ak = getattr(recv[0], "additional_kwargs", {}) or {}
    assert "cache_control" not in ak


@pytest.mark.asyncio
async def test_cache_control_injected_on_astream_too(monkeypatch):
    """The streaming path must apply the same cache_control."""
    wrapper = _get_wrapper(monkeypatch, enabled=True)
    msgs = [SystemMessage(content="SYS_PROMPT"), HumanMessage(content="hi")]
    async for _ in wrapper.astream(msgs):
        pass

    recv = wrapper._llm.received
    ak = getattr(recv[0], "additional_kwargs", {}) or {}
    assert ak.get("cache_control") == {"type": "ephemeral"}
