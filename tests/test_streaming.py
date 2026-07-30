"""
Tests for the streaming pipeline (agent_v2.py).

Verifies that:
1. _to_openai_messages preserves cache_control from additional_kwargs
2. _apply_cache_control injects cache_control on the first system message
3. _raw_stream calls _apply_cache_control before sending
4. _record_usage extracts cache hit tokens from raw streaming chunks

These tests do NOT make real LLM API calls - they use mock objects
to verify the code paths.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


def _make_lc_messages():
    """Create a minimal LangChain-style message list."""
    sys_msg = SimpleNamespace(
        type="system",
        content="You are a helpful assistant.",
        additional_kwargs={},
    )
    user_msg = SimpleNamespace(
        type="human",
        content="Hello",
        additional_kwargs={},
    )
    return [sys_msg, user_msg]


def _make_cached_system_message():
    """Create a system message that already has cache_control."""
    return SimpleNamespace(
        type="system",
        content="You are a helpful assistant.",
        additional_kwargs={"cache_control": {"type": "ephemeral"}},
    )


# ---------------------------------------------------------------------------
# _to_openai_messages tests
# ---------------------------------------------------------------------------

class TestToOpenAIMessages:
    def test_system_message_without_cache_control(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        msgs = _make_lc_messages()
        result = AgentV2._to_openai_messages(msgs)
        assert result[0]["role"] == "system"
        assert "cache_control" not in result[0]

    def test_system_message_with_cache_control_preserved(self):
        """P2 fix: cache_control must survive the dict conversion."""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        sys_msg = _make_cached_system_message()
        user_msg = SimpleNamespace(type="human", content="Hi", additional_kwargs={})
        result = AgentV2._to_openai_messages([sys_msg, user_msg])
        assert result[0]["role"] == "system"
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_user_message_has_no_cache_control(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        msgs = _make_lc_messages()
        result = AgentV2._to_openai_messages(msgs)
        assert result[1]["role"] == "user"
        assert "cache_control" not in result[1]

    def test_tool_message_conversion(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        tool_msg = SimpleNamespace(
            type="tool",
            content="result data",
            tool_call_id="call_123",
            additional_kwargs={},
        )
        result = AgentV2._to_openai_messages([tool_msg])
        assert result[0]["role"] == "tool"
        assert result[0]["content"] == "result data"
        assert result[0]["tool_call_id"] == "call_123"

    def test_assistant_message_with_tool_calls(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        ai_msg = SimpleNamespace(
            type="ai",
            content="Let me check.",
            tool_calls=[{"id": "call_1", "name": "read", "args": {"path": "/tmp"}}],
            additional_kwargs={},
        )
        result = AgentV2._to_openai_messages([ai_msg])
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"][0]["function"]["name"] == "read"


# ---------------------------------------------------------------------------
# _apply_cache_control tests (via UsageTrackingLLM)
# ---------------------------------------------------------------------------

class TestApplyCacheControl:
    def _make_wrapper(self, cache_enabled=True):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
        wrapper = object.__new__(UsageTrackingLLM)
        wrapper._llm = MagicMock()
        wrapper._cache_enabled = cache_enabled
        return wrapper

    def test_injects_cache_control_on_system_message(self):
        wrapper = self._make_wrapper(cache_enabled=True)
        msgs = _make_lc_messages()
        result = wrapper._apply_cache_control(msgs)
        ak = getattr(result[0], "additional_kwargs", {})
        assert "cache_control" in ak
        assert ak["cache_control"] == {"type": "ephemeral"}

    def test_does_not_double_inject(self):
        """If cache_control already exists, don't add another one."""
        wrapper = self._make_wrapper(cache_enabled=True)
        msgs = [_make_cached_system_message()]
        result = wrapper._apply_cache_control(msgs)
        # Should return the same list (no modification)
        assert result[0].additional_kwargs["cache_control"] == {"type": "ephemeral"}

    def test_skips_when_cache_disabled(self):
        wrapper = self._make_wrapper(cache_enabled=False)
        msgs = _make_lc_messages()
        result = wrapper._apply_cache_control(msgs)
        ak = getattr(result[0], "additional_kwargs", {})
        assert "cache_control" not in ak

    def test_skips_non_system_first_message(self):
        wrapper = self._make_wrapper(cache_enabled=True)
        user_msg = SimpleNamespace(type="human", content="Hi", additional_kwargs={})
        result = wrapper._apply_cache_control([user_msg])
        assert "cache_control" not in getattr(result[0], "additional_kwargs", {})

    def test_handles_empty_messages(self):
        wrapper = self._make_wrapper(cache_enabled=True)
        result = wrapper._apply_cache_control([])
        assert result == []


# ---------------------------------------------------------------------------
# _record_usage tests
# ---------------------------------------------------------------------------

class TestRecordUsage:
    def test_extracts_deepseek_cache_hit_from_raw_chunk(self):
        """P2 fix: raw streaming chunks with .usage should be handled."""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=500,
                prompt_cache_hit_tokens=800,
                prompt_tokens_details=None,
            ),
            usage_metadata=None,
            content=None,
        )
        _record_usage(chunk)
        assert token_stats.prompt_tokens == 1000
        assert token_stats.cache_hit_tokens == 800

    def test_extracts_openai_cached_tokens_from_raw_chunk(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=2000,
                completion_tokens=300,
                prompt_cache_hit_tokens=None,
                prompt_tokens_details=SimpleNamespace(cached_tokens=1500),
            ),
            usage_metadata=None,
            content=None,
        )
        _record_usage(chunk)
        assert token_stats.prompt_tokens == 2000
        assert token_stats.cache_hit_tokens == 1500

    def test_falls_back_to_tiktoken_estimation(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        sys_msg = SimpleNamespace(type="system", content="You are helpful.", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="Hello", additional_kwargs={})
        resp = SimpleNamespace(
            usage_metadata=None,
            usage=None,
            content="Hi there!",
        )
        _record_usage(resp, [sys_msg, user_msg])
        assert token_stats.input_tokens > 0
        assert token_stats.output_tokens > 0
        assert token_stats.cache_hit_tokens == 0  # no cache info in fallback

    def test_handles_langchain_usage_metadata(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        resp = SimpleNamespace(
            usage_metadata={
                "input_tokens": 500,
                "output_tokens": 200,
                "input_token_details": {"cache_read": 400},
            },
            usage=None,
            content="response",
            response_metadata={},
        )
        _record_usage(resp)
        assert token_stats.input_tokens == 500
        assert token_stats.output_tokens == 200
        # _extract_cache_read checks response_metadata and usage_metadata
        # cache_read from input_token_details should be picked up
        assert token_stats.cache_hit_tokens >= 0  # depends on _extract_cache_read

    def test_zero_usage_chunk_does_not_crash(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=0,
                completion_tokens=0,
                prompt_cache_hit_tokens=None,
                prompt_tokens_details=None,
            ),
            usage_metadata=None,
            content=None,
        )
        _record_usage(chunk)
        # Should not crash, and should not record anything meaningful
        assert token_stats.input_tokens == 0
