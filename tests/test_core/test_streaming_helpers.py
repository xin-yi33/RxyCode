"""
Tests for utils/streaming.py - UI printing functions and helpers.

Covers: _format_cache_size, _safe_print, print_* functions, _get_memory_info.
"""
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


class TestFormatCacheSize:
    def test_zero(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        assert _format_cache_size(0) == "0"

    def test_small_number(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        assert _format_cache_size(100) == "100"

    def test_under_thousand(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        assert _format_cache_size(999) == "999"

    def test_thousand_plus(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        result = _format_cache_size(1500)
        assert "K" in result

    def test_million_plus(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        result = _format_cache_size(1500000)
        assert "M" in result

    def test_large_number(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        result = _format_cache_size(100000000)
        assert "M" in result

    def test_returns_string(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        assert isinstance(_format_cache_size(42), str)

    def test_negative_returns_string(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _format_cache_size
        # Should handle gracefully
        assert isinstance(_format_cache_size(-1), str)


class TestSafePrint:
    def test_print_none(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import _safe_print
        _safe_print(None)
        captured = capsys.readouterr()
        # Should print newline
        assert "\n" in captured.out or captured.out == ""

    def test_print_string(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import _safe_print
        _safe_print("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_print_text_object(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _safe_print
        # Should not raise
        _safe_print("test text")

    def test_print_no_args(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import _safe_print
        _safe_print()
        captured = capsys.readouterr()
        # Should print empty or newline
        assert isinstance(captured.out, str)


class TestPrintStep:
    def test_print_step(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_step
        print_step(1, 3, "first step")
        captured = capsys.readouterr()
        assert "1/3" in captured.out
        assert "first step" in captured.out

    def test_print_step_done(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_step_done
        print_step_done(2, 3, "second step")
        captured = capsys.readouterr()
        assert "2/3" in captured.out
        assert "second step" in captured.out


class TestPrintThought:
    def test_print_thought(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_thought
        print_thought(1.5)
        captured = capsys.readouterr()
        assert "1.5s" in captured.out

    def test_print_thought_zero(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_thought
        print_thought(0.0)
        captured = capsys.readouterr()
        assert "0.0s" in captured.out


class TestPrintToolCall:
    def test_print_tool_call(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_tool_call
        print_tool_call("read", "file.txt")
        captured = capsys.readouterr()
        assert "read" in captured.out
        assert "file.txt" in captured.out


class TestPrintToolResult:
    def test_print_success_result(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_tool_result
        print_tool_result("success message", "success")
        captured = capsys.readouterr()
        assert "success message" in captured.out

    def test_print_error_result(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_tool_result
        print_tool_result("error message", "error")
        captured = capsys.readouterr()
        assert "error message" in captured.out

    def test_print_warning_result(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_tool_result
        print_tool_result("warning message", "warning")
        captured = capsys.readouterr()
        assert "warning message" in captured.out

    def test_print_long_result_truncated(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_tool_result
        long_result = "x" * 300
        print_tool_result(long_result, "success")
        captured = capsys.readouterr()
        assert "..." in captured.out


class TestPrintMessages:
    def test_print_success(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_success
        print_success("operation done")
        captured = capsys.readouterr()
        assert "operation done" in captured.out

    def test_print_error(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_error
        print_error("something failed")
        captured = capsys.readouterr()
        assert "something failed" in captured.out

    def test_print_info(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_info
        print_info("informational")
        captured = capsys.readouterr()
        assert "informational" in captured.out

    def test_print_warning(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_warning
        print_warning("be careful")
        captured = capsys.readouterr()
        assert "be careful" in captured.out

    def test_print_goodbye(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_goodbye
        print_goodbye()
        # Should not crash
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)


class TestPrintChatFunctions:
    def test_print_chat_saved(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_chat_saved
        print_chat_saved("my chat")
        captured = capsys.readouterr()
        assert "my chat" in captured.out

    def test_print_chat_loaded(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_chat_loaded
        print_chat_loaded("my chat")
        captured = capsys.readouterr()
        assert "my chat" in captured.out

    def test_print_chat_list_empty(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_chat_list
        print_chat_list([])
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)

    def test_print_chat_list_with_chats(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_chat_list
        chats = [{"name": "chat1", "preview": "hello"}, {"name": "chat2", "preview": "world"}]
        print_chat_list(chats)
        captured = capsys.readouterr()
        assert "chat1" in captured.out
        assert "chat2" in captured.out

    def test_print_chat_history_header(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_chat_history_header
        print_chat_history_header("History")
        captured = capsys.readouterr()
        assert "History" in captured.out


class TestPrintSubagent:
    def test_print_subagent_start(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_subagent_start
        print_subagent_start("do something")
        captured = capsys.readouterr()
        assert "do something" in captured.out

    def test_print_subagent_complete(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_subagent_complete
        print_subagent_complete("result")
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)


class TestPrintAutoResume:
    def test_print_auto_resume_empty(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_auto_resume_prompt
        print_auto_resume_prompt([])
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)

    def test_print_auto_resume_with_chats(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_auto_resume_prompt
        chats = [{"name": "old chat", "preview": "some preview"}]
        print_auto_resume_prompt(chats)
        captured = capsys.readouterr()
        assert "old chat" in captured.out

    def test_print_auto_resume_limits_to_10(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_auto_resume_prompt
        chats = [{"name": f"chat{i}", "preview": "p"} for i in range(20)]
        print_auto_resume_prompt(chats)
        captured = capsys.readouterr()
        assert "chat0" in captured.out
        assert "chat9" in captured.out
        assert "chat10" not in captured.out  # Only first 10


class TestPrintCommandHint:
    def test_print_command_hint(self, capsys):
        from RxyCode.RxyCode1_1_0.utils.streaming import print_command_hint
        print_command_hint()
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)


class TestGetMemoryInfo:
    def test_returns_tuple(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _get_memory_info
        result = _get_memory_info()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_floats(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import _get_memory_info
        mem_mb, mem_pct = _get_memory_info()
        assert isinstance(mem_mb, float)
        assert isinstance(mem_pct, float)

    def test_psutil_available(self):
        """Test with psutil available (should be installed in test env)."""
        from RxyCode.RxyCode1_1_0.utils.streaming import _get_memory_info
        mem_mb, mem_pct = _get_memory_info()
        # If psutil is available, should return non-zero values
        if mem_mb > 0:
            assert mem_pct > 0

    def test_psutil_not_available(self):
        """Test when psutil is not installed."""
        from RxyCode.RxyCode1_1_0.utils import streaming
        with patch.dict("sys.modules", {"psutil": None}):
            result = streaming._get_memory_info()
            assert result == (0.0, 0.0)
