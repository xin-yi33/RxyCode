"""
Tests for utils/streaming.py - TokenStats and streaming utilities.

Covers: token counting, cache hit rate, context tracking, warnings, reset.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestTokenStats:
    def _make_stats(self):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        return TokenStats()

    def test_default_values(self):
        stats = self._make_stats()
        assert stats.input_tokens == 0
        assert stats.output_tokens == 0
        assert stats.cache_hit_tokens == 0
        assert stats.cache_hit_rate == 0.0
        assert stats.context_used == 0
        # context_max defaults to 256000 (a reasonable default)
        assert stats.context_max == 256000

    def test_add_real_usage_basic(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 500, 0)
        assert stats.input_tokens == 1000
        assert stats.output_tokens == 500
        assert stats.cache_hit_tokens == 0

    def test_add_real_usage_with_cache_hit(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 500, 800)
        assert stats.cache_hit_tokens == 800
        assert stats.cache_hit_rate == pytest.approx(80.0, rel=0.1)

    def test_add_real_usage_accumulates(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 500, 0)
        stats.add_real_usage(2000, 1000, 1000)
        assert stats.input_tokens == 3000
        assert stats.output_tokens == 1500
        assert stats.cache_hit_tokens == 1000

    def test_cache_hit_rate_calculation(self):
        stats = self._make_stats()
        stats.add_real_usage(3000, 0, 2000)
        assert stats.cache_hit_rate == pytest.approx(66.67, rel=0.01)

    def test_cache_hit_rate_zero_input(self):
        stats = self._make_stats()
        stats.add_real_usage(0, 0, 0)
        assert stats.cache_hit_rate == 0.0

    def test_application_cache_metrics_are_separate_from_provider_prefix_cache(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 100, 250)
        stats.record_application_cache("precise", hit=True)
        stats.record_application_cache("semantic", hit=False)

        assert stats.cache_hit_rate == pytest.approx(25.0)
        assert stats.application_cache_hits == {"precise": 1, "semantic": 0}
        assert stats.application_cache_misses == {"precise": 0, "semantic": 1}

    def test_application_cache_snapshot_has_explicit_denominators_and_rates(self):
        stats = self._make_stats()
        stats.record_application_cache("precise", hit=True)
        stats.record_application_cache("precise", hit=False)
        stats.record_application_cache("precise", bypass=True)
        stats.record_application_cache("semantic", bypass=True)

        snapshot = stats.get_application_cache_stats()

        assert snapshot["precise"] == {
            "requests": 3,
            "eligible": 2,
            "bypassed": 1,
            "hits": 1,
            "misses": 1,
            "hit_rate": 50.0,
            "miss_rate": 50.0,
            "eligibility_rate": 66.67,
            "bypass_rate": 33.33,
        }
        assert snapshot["semantic"]["eligible"] == 0
        assert snapshot["semantic"]["bypass_rate"] == 100.0
        assert snapshot["semantic"]["hit_rate"] == 0.0

    def test_reset_clears_application_cache_metrics(self):
        stats = self._make_stats()
        stats.record_application_cache("precise", hit=True)
        stats.record_application_cache("semantic", bypass=True)
        stats.reset()
        assert stats.application_cache_hits == {"precise": 0, "semantic": 0}
        assert stats.application_cache_misses == {"precise": 0, "semantic": 0}
        assert stats.application_cache_bypasses == {"precise": 0, "semantic": 0}

    def test_reset_clears_all(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 500, 800)
        stats.reset()
        assert stats.input_tokens == 0
        assert stats.output_tokens == 0
        assert stats.cache_hit_tokens == 0
        assert stats.cache_hit_rate == 0.0

    def test_reset_clears_context(self):
        stats = self._make_stats()
        stats.update_context(50000, 256000)
        stats.reset()
        assert stats.context_used == 0
        # reset sets context_max back to 256000 default
        assert stats.context_max == 256000

    def test_update_context(self):
        stats = self._make_stats()
        stats.update_context(50000, 256000)
        assert stats.context_used == 50000
        assert stats.context_max == 256000

    def test_update_context_only_used(self):
        stats = self._make_stats()
        stats.update_context(10000)
        assert stats.context_used == 10000

    def test_should_warn_under_threshold(self):
        stats = self._make_stats()
        stats.update_context(10000, 256000)
        assert stats.should_warn_about_token_budget() is False

    def test_should_warn_at_threshold(self):
        stats = self._make_stats()
        # 220000/256000 = 0.859 > 0.85
        stats.update_context(220000, 256000)
        assert stats.should_warn_about_token_budget() is True

    def test_should_warn_zero_max(self):
        stats = self._make_stats()
        assert stats.should_warn_about_token_budget() is False

    def test_get_context_warning_none(self):
        stats = self._make_stats()
        stats.update_context(10000, 256000)
        assert stats.get_context_warning() is None

    def test_get_context_warning_warning(self):
        stats = self._make_stats()
        stats.update_context(220000, 256000)
        warning = stats.get_context_warning()
        assert warning is not None
        assert "Warning" in warning

    def test_get_context_warning_critical(self):
        stats = self._make_stats()
        stats.update_context(250000, 256000)
        warning = stats.get_context_warning()
        assert warning is not None
        assert "CRITICAL" in warning

    def test_get_context_warning_includes_percentage(self):
        stats = self._make_stats()
        stats.update_context(220000, 256000)
        warning = stats.get_context_warning()
        assert "%" in warning

    def test_get_context_warning_includes_token_count(self):
        stats = self._make_stats()
        stats.update_context(220000, 256000)
        warning = stats.get_context_warning()
        assert "220000" in warning or "256000" in warning

    def test_warning_threshold_is_085(self):
        stats = self._make_stats()
        assert stats.TOKEN_WARNING_THRESHOLD == 0.85

    def test_multiple_add_real_usage_calls(self):
        stats = self._make_stats()
        for i in range(10):
            stats.add_real_usage(100, 50, 50)
        assert stats.input_tokens == 1000
        assert stats.output_tokens == 500
        assert stats.cache_hit_tokens == 500

    def test_cache_hit_rate_after_multiple_calls(self):
        stats = self._make_stats()
        stats.add_real_usage(1000, 0, 500)
        stats.add_real_usage(1000, 0, 0)
        # Rate should be 500/2000 = 25%
        assert stats.cache_hit_rate == pytest.approx(25.0, rel=0.1)


class TestEstimateTokens:
    def test_empty_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_short_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        result = _estimate_tokens("hello")
        assert result > 0
        assert result < 10

    def test_long_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        result = _estimate_tokens("a" * 1000)
        assert result > 100

    def test_none_input(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        assert _estimate_tokens(None) == 0

    def test_unicode_string(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        result = _estimate_tokens("你好世界")
        assert result > 0

    def test_returns_int(self):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens
        result = _estimate_tokens("test string")
        assert isinstance(result, int)


class TestExtractCacheRead:
    def _extract(self, resp):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import _extract_cache_read
        return _extract_cache_read(resp)

    def test_deepseek_cache_hit(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(
            response_metadata={
                "token_usage": {"prompt_cache_hit_tokens": 500},
            },
            usage_metadata={},
        )
        assert self._extract(resp) == 500

    def test_openai_cached_tokens(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(
            response_metadata={
                "token_usage": {"prompt_tokens_details": {"cached_tokens": 300}},
            },
            usage_metadata={},
        )
        assert self._extract(resp) == 300

    def test_langchain_cache_read(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(
            response_metadata={},
            usage_metadata={"input_token_details": {"cache_read": 200}},
        )
        assert self._extract(resp) == 200

    def test_no_cache_info(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(response_metadata={}, usage_metadata={})
        assert self._extract(resp) == 0

    def test_empty_usage_metadata(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(response_metadata={}, usage_metadata=None)
        assert self._extract(resp) == 0

    def test_no_usage_metadata_attr(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(response_metadata={})
        assert self._extract(resp) == 0

    def test_deepseek_takes_priority(self):
        from types import SimpleNamespace
        resp = SimpleNamespace(
            response_metadata={
                "token_usage": {
                    "prompt_cache_hit_tokens": 500,
                    "prompt_tokens_details": {"cached_tokens": 300},
                },
            },
            usage_metadata={},
        )
        assert self._extract(resp) == 500

    def test_none_resp(self):
        assert self._extract(None) == 0
