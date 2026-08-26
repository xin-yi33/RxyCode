"""P6 / FX-CB7: Child cache tokens must not count as Primary."""

from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.session import primary_usage_counters
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats


def test_child_cache_tokens_are_not_counted_as_primary() -> None:
    """Shipped Session snapshot fails if Child usage is mixed into Primary."""
    token_stats.reset()
    try:
        token_stats.add_real_usage(1000, 0, 970)
        scope_token, scoped = token_stats.begin_usage_scope()
        try:
            token_stats.add_real_usage(5000, 0, 100)
        finally:
            token_stats.end_usage_scope(scope_token)
        snap = primary_usage_counters()
        assert snap["input_tokens"] == 1000
        assert snap["cache_hit_tokens"] == 970
        assert snap["cache_hit_rate"] == pytest.approx(97.0)
        assert scoped == {
            "input_tokens": 5000,
            "output_tokens": 0,
            "cache_hit_tokens": 100,
        }
        mixed = token_stats.cache_hit_tokens / token_stats.prompt_tokens * 100
        assert mixed == pytest.approx(1070 / 6000 * 100)
        assert snap["cache_hit_rate"] > mixed
    finally:
        token_stats.reset()


def test_shared_prefix_scope_counts_as_primary() -> None:
    token_stats.reset()
    try:
        token, scoped = token_stats.begin_usage_scope(count_as_primary=True)
        try:
            token_stats.add_real_usage(2000, 0, 1940)
        finally:
            token_stats.end_usage_scope(token)
        snap = primary_usage_counters()
        assert snap["input_tokens"] == 2000
        assert snap["cache_hit_tokens"] == 1940
        assert snap["cache_hit_rate"] == pytest.approx(97.0)
        assert scoped["cache_hit_tokens"] == 1940
    finally:
        token_stats.reset()
