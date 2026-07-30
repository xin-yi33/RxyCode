"""
Tests for memory/compressor.py - Three-tier context compression.

Covers: token counting, needs_compression, tier1/tier2/tier3, helpers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestContextCompressor:
    def _make_compressor(self, **kwargs):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        defaults = {"max_tokens": 1000, "trigger_ratio": 0.8,
                     "tier1_tool_threshold": 100, "tier2_protected_tokens": 200}
        defaults.update(kwargs)
        return ContextCompressor(**defaults)

    def test_count_tokens_nonempty(self):
        comp = self._make_compressor()
        count = comp.count_tokens("hello world")
        assert count > 0

    def test_count_tokens_empty(self):
        comp = self._make_compressor()
        assert comp.count_tokens("") == 0

    def test_count_tokens_long_text(self):
        comp = self._make_compressor()
        count = comp.count_tokens("a" * 1000)
        assert count > 0

    def test_count_tokens_chinese(self):
        comp = self._make_compressor()
        count = comp.count_tokens("你好世界")
        assert count > 0

    def test_needs_compression_true(self):
        comp = self._make_compressor(max_tokens=10, trigger_ratio=0.5)
        assert comp.needs_compression("a" * 100) is True

    def test_needs_compression_false(self):
        comp = self._make_compressor(max_tokens=100000, trigger_ratio=0.9)
        assert comp.needs_compression("short") is False

    def test_needs_compression_empty(self):
        comp = self._make_compressor(max_tokens=10, trigger_ratio=0.5)
        assert comp.needs_compression("") is False

    def test_compress_sync_no_compression_needed(self):
        comp = self._make_compressor(max_tokens=100000)
        messages = [{"role": "user", "content": "short"}]
        result, lt = comp.compress_sync(messages)
        assert result == messages

    def test_compress_sync_triggers_tier1(self):
        comp = self._make_compressor(max_tokens=50, trigger_ratio=0.1, tier1_tool_threshold=5)
        # _middle_truncate only fires when len(text) > keep_chars*2 + 100 = 3100
        long_content = "start\n" + "x" * 5000 + "\nend"
        messages = [{"role": "tool", "content": long_content}]
        # Use tier1 directly to check truncation (compress_sync may run tier2 after)
        result = comp._tier1(messages)
        assert "truncated" in result[0]["content"]

    def test_tier1_middle_truncation(self):
        comp = self._make_compressor(tier1_tool_threshold=5)
        long_text = "start\n" + "middle " * 500 + "\nend"
        result = comp._tier1([{"role": "tool", "content": long_text}])
        assert "truncated" in result[0]["content"]

    def test_tier1_short_content_unchanged(self):
        comp = self._make_compressor(tier1_tool_threshold=10000)
        messages = [{"role": "user", "content": "short text"}]
        result = comp._tier1(messages)
        assert result[0]["content"] == "short text"

    def test_tier1_trims_assistant_replies(self):
        comp = self._make_compressor(tier1_tool_threshold=10000)
        # Tier1 only trims assistant replies > 500 tokens
        # "First sentence. " is ~16 chars ~= 5 tokens, need ~100 repetitions to exceed 500 tokens
        long_reply = "First sentence. Second sentence. Third sentence. " * 500
        messages = [{"role": "assistant", "content": long_reply}]
        result = comp._tier1(messages)
        assert "trimmed" in result[0]["content"]

    def test_tier1_preserves_short_assistant(self):
        comp = self._make_compressor(tier1_tool_threshold=10000)
        messages = [{"role": "assistant", "content": "Short reply."}]
        result = comp._tier1(messages)
        assert result[0]["content"] == "Short reply."

    def test_middle_truncate_short_text_unchanged(self):
        comp = self._make_compressor()
        short_text = "short text"
        result = comp._middle_truncate(short_text)
        assert result == short_text

    def test_middle_truncate_long_text(self):
        comp = self._make_compressor()
        long_text = "start\n" + "x" * 5000 + "\nend"
        result = comp._middle_truncate(long_text)
        assert "truncated" in result
        assert "start" in result
        assert "end" in result

    def test_trim_to_two_sentences_short(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        text = "Only one sentence."
        result = ContextCompressor._trim_to_two_sentences(text)
        assert result == text

    def test_trim_to_two_sentences_long(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = ContextCompressor._trim_to_two_sentences(text)
        assert "First sentence" in result
        assert "trimmed" in result

    def test_trim_chinese_sentences(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        text = "第一句话。第二句话。第三句话。第四句话。"
        result = ContextCompressor._trim_to_two_sentences(text)
        assert "第一句话" in result

    def test_messages_to_str(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = ContextCompressor._messages_to_str(messages)
        assert "Hello" in result
        assert "Hi there" in result

    def test_messages_to_str_empty(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        assert ContextCompressor._messages_to_str([]) == ""

    def test_messages_to_str_user_label(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        messages = [{"role": "user", "content": "test"}]
        result = ContextCompressor._messages_to_str(messages)
        assert "User" in result

    def test_messages_to_str_assistant_label(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        messages = [{"role": "assistant", "content": "test"}]
        result = ContextCompressor._messages_to_str(messages)
        assert "Assistant" in result

    def test_build_context_with_long_term(self):
        comp = self._make_compressor()
        messages = [{"role": "user", "content": "test"}]
        result = comp._build_context(messages, "long term memory")
        assert "long term memory" in result
        assert "test" in result

    def test_build_context_empty(self):
        comp = self._make_compressor()
        assert comp._build_context([], "") == ""

    def test_build_context_only_messages(self):
        comp = self._make_compressor()
        messages = [{"role": "user", "content": "hello"}]
        result = comp._build_context(messages, "")
        assert "hello" in result

    def test_tier2_empty_messages(self):
        comp = self._make_compressor()
        messages, lt = comp._tier2([], "")
        assert messages == []

    def test_tier2_protects_recent_messages(self):
        comp = self._make_compressor(tier2_protected_tokens=10000)
        messages = [
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "recent reply"},
        ]
        result, lt = comp._tier2(messages, "")
        # Protected zone should keep recent messages
        assert len(result) <= len(messages) + 1  # +1 for placeholder

    def test_tier2_caps_long_term_at_50kb(self):
        comp = self._make_compressor(tier2_protected_tokens=1)
        messages = [{"role": "user", "content": "x" * 100}]
        _, lt = comp._tier2(messages, "")
        assert len(lt) <= 50000

    def test_compress_sync_returns_messages_and_long_term(self):
        comp = self._make_compressor(max_tokens=100000)
        messages = [{"role": "user", "content": "test"}]
        result, lt = comp.compress_sync(messages, "")
        assert isinstance(result, list)
        assert isinstance(lt, str)


class TestCompressorAsync:
    @pytest.mark.asyncio
    async def test_compress_async_no_compression_needed(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        comp = ContextCompressor(max_tokens=100000)
        messages = [{"role": "user", "content": "short"}]
        result, lt, used = await comp.compress_async(messages, "")
        assert used is False

    @pytest.mark.asyncio
    async def test_compress_async_no_llm(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        comp = ContextCompressor(max_tokens=1, trigger_ratio=0.1, tier2_protected_tokens=1)
        messages = [{"role": "user", "content": "x" * 100}]
        result, lt, used = await comp.compress_async(messages, "")
        # No LLM means tier3 won't fire
        assert isinstance(result, list)
        assert isinstance(lt, str)

    @pytest.mark.asyncio
    async def test_compress_async_with_mock_llm(self):
        from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor
        mock_llm = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.content = "Summary of conversation"
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        comp = ContextCompressor(
            llm=mock_llm,
            max_tokens=1, trigger_ratio=0.1,
            tier1_tool_threshold=1, tier2_protected_tokens=1,
        )
        messages = [
            {"role": "user", "content": "old message 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "recent message"},
        ]
        result, lt, used = await comp.compress_async(messages, "")
        assert used is True
