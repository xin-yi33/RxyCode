"""A8: usage/reasoning extraction delegates to provider; capability gates."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from langchain_core.messages import HumanMessage

from RxyCode.RxyCode1_1_0.config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
)
from RxyCode.RxyCode1_1_0.core import providers
from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM, _merged_usage_dict, _record_usage


class _FakeResp:
    def __init__(self, usage_metadata=None, response_metadata=None, usage=None, content=""):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}
        self.usage = usage
        self.content = content


class _RawUsage:
    def __init__(self, prompt_tokens, completion_tokens, **extra):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        for key, value in extra.items():
            setattr(self, key, value)

    def model_dump(self):
        return {key: value for key, value in vars(self).items()}


class _RecordingProvider(providers.BaseProvider):
    def __init__(self):
        self.last_usage = None
        self.last_caps = None

    def extract_cache_read(self, usage, caps):
        self.last_usage = usage
        self.last_caps = caps
        return super().extract_cache_read(usage, caps)


# --- 1. merged usage dict --------------------------------------------------

def test_merged_usage_dict_combines_all_sources():
    resp = _FakeResp(
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "usage": {"prompt_cache_hit_tokens": 3},
        },
        response_metadata={"token_usage": {"prompt_tokens_details": {"cached_tokens": 9}}},
    )
    merged = _merged_usage_dict(resp)
    assert merged["prompt_cache_hit_tokens"] == 3
    assert merged["prompt_tokens_details"]["cached_tokens"] == 9
    assert merged["input_tokens"] == 10


# --- 2. non-streaming delegation -------------------------------------------

def test_record_usage_delegates_cache_read_non_streaming():
    spy = _RecordingProvider()
    caps = DEFAULT_CAPABILITIES
    resp = _FakeResp(
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "input_token_details": {"cache_read": 7},
        },
    )
    inp, out = _record_usage(resp, provider=spy, caps=caps)
    assert (inp, out) == (10, 5)
    assert spy.last_caps is caps
    assert spy.last_usage.get("input_token_details", {}).get("cache_read") == 7


# --- 3. raw streaming chunk delegation -------------------------------------

def test_record_usage_delegates_cache_read_raw_streaming():
    spy = _RecordingProvider()
    resp = _FakeResp(
        usage=_RawUsage(20, 8, prompt_cache_hit_tokens=4),
    )
    inp, out = _record_usage(resp, provider=spy, caps=DEFAULT_CAPABILITIES)
    assert (inp, out) == (20, 8)
    assert spy.last_usage.get("prompt_cache_hit_tokens") == 4


# --- 4. UsageTrackingLLM wiring --------------------------------------------

async def test_usage_tracking_llm_delegates_to_constructed_provider():
    resp = _FakeResp(
        usage_metadata={
            "input_tokens": 1,
            "output_tokens": 2,
            "input_token_details": {"cache_read": 5},
        },
    )
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value=resp)
    inner._apply_cache_control = lambda msgs: msgs
    spy = _RecordingProvider()
    llm = UsageTrackingLLM(inner, provider=spy, capabilities=DEFAULT_CAPABILITIES)
    await llm.ainvoke([HumanMessage(content="hi")])
    assert spy.last_usage is not None
    assert spy.last_usage.get("input_token_details", {}).get("cache_read") == 5


# --- 5. cache_control capability gate --------------------------------------

def test_apply_cache_control_skipped_when_prompt_cache_unsupported():
    caps = ModelCapabilities(supports_prompt_cache=False)
    llm = UsageTrackingLLM(MagicMock(), provider=providers.BaseProvider(), capabilities=caps)
    llm._cache_enabled = True
    msg = MagicMock(type="system", content="sys")
    msg.additional_kwargs = {}
    msgs = [msg]
    assert llm._apply_cache_control(msgs) is msgs


def test_apply_cache_control_applies_when_supported():
    llm = UsageTrackingLLM(
        MagicMock(), provider=providers.BaseProvider(), capabilities=DEFAULT_CAPABILITIES
    )
    llm._cache_enabled = True
    msg = MagicMock(type="system", content="sys")
    msg.additional_kwargs = {}
    msgs = [msg]
    out = llm._apply_cache_control(msgs)
    assert out is not msgs
    assert out[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}


# --- 6. bind_tools capability gate -----------------------------------------

def test_bind_tools_raises_when_function_calling_unsupported():
    caps = ModelCapabilities(supports_function_calling=False)
    llm = UsageTrackingLLM(MagicMock(), provider=providers.BaseProvider(), capabilities=caps)
    with pytest.raises(ValueError, match="function calling"):
        llm.bind_tools([MagicMock()])


# --- 7. _raw_stream capability gate ----------------------------------------

async def test_raw_stream_raises_when_function_calling_unsupported():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent.model_config = {
        "model_name": "fake-no-fc",
        "temperature": 0.7,
        "max_tokens": 100,
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
    }
    agent._capabilities = ModelCapabilities(supports_function_calling=False)
    agent._provider = providers.BaseProvider()
    agent._llm = MagicMock()
    agent._llm._apply_cache_control = lambda msgs: msgs
    agent._rate_limiter = None
    agent._rate_reserved_output_tokens = 0
    agent._rate_limit_timeout = None
    with pytest.raises(ValueError, match="function calling"):
        async for _ in agent._raw_stream([HumanMessage(content="hi")], tools=[MagicMock()]):
            pass
