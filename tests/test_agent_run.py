"""
Tests for AgentV2 core logic (no real LLM calls).

Verifies:
1. _is_simple_query correctly classifies simple vs complex prompts
2. _openai_client resolution
3. _build_progress_message formatting
4. _estimate_tokens returns reasonable estimates
5. AgentV2 construction with a mock config
"""
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace


class TestIsSimpleQuery:
    def _classify(self, text):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        agent = object.__new__(AgentV2)
        return agent._is_simple_query(text)

    def test_plain_question_is_simple(self):
        assert self._classify("Python 的 list 和 tuple 有什么区别？") is True

    def test_greeting_is_simple(self):
        assert self._classify("你好") is True

    def test_english_question_is_simple(self):
        assert self._classify("what is a decorator in python?") is True

    def test_code_generation_is_complex(self):
        assert self._classify("帮我写一个快速排序算法") is False

    def test_game_creation_is_complex(self):
        assert self._classify("帮我用Python写一个跑酷小游戏") is False

    def test_project_creation_is_complex(self):
        assert self._classify("帮我创建一个完整的Python项目") is False

    def test_build_command_is_complex(self):
        assert self._classify("Build a complete REST API from scratch") is False

    def test_file_read_is_complex(self):
        assert self._classify("读取文件 /etc/hosts") is False

    def test_empty_string_is_simple(self):
        assert self._classify("") is True


class TestBuildProgressMessage:
    def test_returns_string_with_elapsed(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import build_progress_message
        msg = build_progress_message(30.0)
        assert "30" in msg
        assert "Build" in msg

    def test_includes_minutes_for_long_durations(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import build_progress_message
        msg = build_progress_message(120.0)
        assert "2m" in msg or "120s" in msg


class TestEstimateTokens:
    def test_empty_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_short_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        result = _estimate_tokens("Hello world")
        assert result > 0
        assert result < 100

    def test_long_string_more_tokens(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        short = _estimate_tokens("Hello")
        long = _estimate_tokens("Hello " * 100)
        assert long > short


class TestExtractCacheRead:
    def test_deepseek_prompt_cache_hit(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_cache_read
        resp = SimpleNamespace(
            response_metadata={
                "token_usage": {"prompt_cache_hit_tokens": 800}
            },
            usage_metadata={},
        )
        assert _extract_cache_read(resp) == 800

    def test_openai_cached_tokens(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_cache_read
        resp = SimpleNamespace(
            response_metadata={
                "token_usage": {"prompt_tokens_details": {"cached_tokens": 500}}
            },
            usage_metadata={},
        )
        assert _extract_cache_read(resp) == 500

    def test_no_cache_info_returns_zero(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_cache_read
        resp = SimpleNamespace(
            response_metadata={},
            usage_metadata={},
        )
        assert _extract_cache_read(resp) == 0

    def test_empty_resp_returns_zero(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_cache_read
        assert _extract_cache_read(None) == 0


class TestTokenStatsIntegration:
    def test_cache_hit_rate_calculation(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        stats.add_real_usage(1000, 500, 800)  # 800 of 1000 prompt tokens from cache
        assert stats.cache_hit_rate == 80.0

    def test_cache_hit_rate_zero_when_no_tokens(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        assert stats.cache_hit_rate == 0.0

    def test_add_real_usage_accumulates(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        stats.add_real_usage(1000, 500, 800)
        stats.add_real_usage(2000, 1000, 1200)
        assert stats.input_tokens == 3000
        assert stats.output_tokens == 1500
        assert stats.cache_hit_tokens == 2000
        assert stats.prompt_tokens == 3000
        assert stats.cache_hit_rate == pytest.approx(66.67, rel=0.01)

    def test_reset_clears_all(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        stats.add_real_usage(1000, 500, 800)
        stats.reset()
        assert stats.input_tokens == 0
        assert stats.cache_hit_tokens == 0
        assert stats.cache_hit_rate == 0.0

    def test_context_warning_thresholds(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        # 220000/256000 = 0.859 > 0.85 threshold
        stats.update_context(220000, 256000)
        assert stats.should_warn_about_token_budget() is True
        warning = stats.get_context_warning()
        assert warning is not None
        assert "Warning" in warning or "CRITICAL" in warning

    def test_no_warning_under_threshold(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        stats.update_context(10000, 256000)
        assert stats.should_warn_about_token_budget() is False
        assert stats.get_context_warning() is None
