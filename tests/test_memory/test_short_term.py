"""
Tests for memory/short_term.py - Short-term conversation memory.

Covers: message storage, context retrieval, overflow, pop, clear, serialization.
"""
import pytest
from unittest.mock import MagicMock


class TestShortTermMemory:
    def _make(self, window_size=10):
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory
        return ShortTermMemory(window_size=window_size)

    def test_default_window_size(self):
        stm = self._make()
        assert stm.window_size == 10

    def test_custom_window_size(self):
        stm = self._make(window_size=5)
        assert stm.window_size == 5

    def test_empty_memory(self):
        stm = self._make()
        assert stm.message_count == 0
        assert stm.turn_count == 0

    def test_add_user_message(self):
        stm = self._make()
        stm.add_user_message("hello")
        assert stm.message_count == 1
        assert stm.turn_count == 1

    def test_add_ai_message(self):
        stm = self._make()
        stm.add_ai_message("hi there")
        assert stm.message_count == 1
        assert stm.turn_count == 0

    def test_add_interaction(self):
        stm = self._make()
        stm.add_user_message("question")
        stm.add_ai_message("answer")
        assert stm.message_count == 2
        assert stm.turn_count == 1

    def test_get_messages(self):
        stm = self._make()
        stm.add_user_message("hello")
        msgs = stm.get_messages()
        assert len(msgs) == 1

    def test_get_messages_as_dicts(self):
        stm = self._make()
        stm.add_user_message("hello")
        stm.add_ai_message("world")
        dicts = stm.get_messages_as_dicts()
        assert len(dicts) == 2
        assert dicts[0]["role"] == "user"
        assert dicts[1]["role"] == "assistant"

    def test_get_context_string(self):
        stm = self._make()
        stm.add_user_message("hello")
        stm.add_ai_message("world")
        ctx = stm.get_context_string()
        assert "User" in ctx
        assert "Assistant" in ctx
        assert "hello" in ctx
        assert "world" in ctx

    def test_get_context_string_empty(self):
        stm = self._make()
        ctx = stm.get_context_string()
        assert ctx == ""

    def test_clear(self):
        stm = self._make()
        stm.add_user_message("hello")
        stm.add_ai_message("world")
        stm.clear()
        assert stm.message_count == 0
        assert stm.turn_count == 0

    def test_load_from_dicts(self):
        stm = self._make()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        stm.load_from_dicts(messages)
        assert stm.message_count == 2
        assert stm.turn_count == 1

    def test_load_from_dicts_clears_first(self):
        stm = self._make()
        stm.add_user_message("old message")
        stm.load_from_dicts([
            {"role": "user", "content": "new"},
        ])
        assert stm.message_count == 1

    def test_is_overflow_false(self):
        stm = self._make()
        stm.add_user_message("msg")
        assert stm.is_overflow(threshold=30) is False

    def test_is_overflow_true(self):
        stm = self._make(window_size=20)
        for i in range(35):
            stm.add_user_message(f"msg {i}")
        # window_size=20 means maxlen=40, so all 35 fit
        assert stm.is_overflow(threshold=30) is True

    def test_pop_oldest_pair(self):
        stm = self._make()
        stm.add_user_message("first question")
        stm.add_ai_message("first answer")
        pair = stm.pop_oldest_pair()
        assert pair is not None
        assert pair[0] == "first question"
        assert pair[1] == "first answer"
        assert stm.message_count == 0

    def test_pop_oldest_pair_empty(self):
        stm = self._make()
        pair = stm.pop_oldest_pair()
        assert pair is None

    def test_pop_oldest_pair_single_message(self):
        stm = self._make()
        stm.add_user_message("only user msg")
        pair = stm.pop_oldest_pair()
        assert pair is None

    def test_message_count_after_multiple_adds(self):
        stm = self._make()
        for i in range(20):
            stm.add_user_message(f"msg {i}")
        assert stm.message_count == 20

    def test_window_size_limit(self):
        stm = self._make(window_size=2)
        for i in range(10):
            stm.add_user_message(f"msg {i}")
        # window_size=2 means deque maxlen=4
        assert stm.message_count <= 4

    def test_get_relevant_context_empty(self):
        stm = self._make()
        ctx = stm.get_relevant_context("query")
        assert ctx == ""

    def test_get_relevant_context_with_match(self):
        stm = self._make()
        stm.add_user_message("python programming")
        stm.add_ai_message("python is great")
        ctx = stm.get_relevant_context("python")
        assert "python" in ctx.lower()

    def test_get_relevant_context_no_match(self):
        stm = self._make()
        stm.add_user_message("java programming")
        ctx = stm.get_relevant_context("python")
        # Should still return something (maybe empty or low-scored)
        assert isinstance(ctx, str)

    def test_get_context_string_truncation(self):
        stm = self._make()
        long_msg = "x" * 600
        stm.add_user_message(long_msg)
        ctx = stm.get_context_string()
        assert "..." in ctx

    def test_turn_count_increments_on_user_only(self):
        stm = self._make()
        stm.add_user_message("q1")
        stm.add_ai_message("a1")
        stm.add_user_message("q2")
        assert stm.turn_count == 2

    def test_load_from_dicts_updates_turn_count(self):
        stm = self._make()
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        stm.load_from_dicts(messages)
        assert stm.turn_count == 2

    def test_load_from_dicts_ignores_ui_only_session_roles(self):
        stm = self._make()
        stm.load_from_dicts([
            {"role": "user", "content": "question"},
            {"role": "thinking", "content": "private reasoning"},
            {"role": "tool", "content": "tool output"},
            {"role": "system", "content": "ui notice"},
            {"role": "assistant", "content": "answer"},
        ])

        assert stm.get_messages_as_dicts() == [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
