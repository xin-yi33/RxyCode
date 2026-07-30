"""
Tests for TokenStats cost calculation driven by config pricing.

- config/settings.py _default_config has a ``pricing: {}`` section
  ({model_name: {input: $/M tokens, output: $/M tokens}})
- billing_amount uses the configured per-model price
- When no price is configured for the active model, billing_amount is None
  (do not show a wrong price)
"""
import pytest
from unittest.mock import patch


class TestDefaultConfigPricing:
    def test_default_config_has_pricing_section(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert "pricing" in cfg
        assert cfg["pricing"] == {}


class TestBillingAmount:
    def _make_stats(self, model=None):
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats
        stats = TokenStats()
        if model:
            stats.set_model(model)
        return stats

    def test_no_model_configured_returns_none(self):
        stats = self._make_stats()
        stats.add_real_usage(1_000_000, 1_000_000, 0)
        with patch(
            "RxyCode.RxyCode1_1_0.utils.streaming.load_config",
            return_value={"pricing": {}},
        ):
            assert stats.billing_amount is None

    def test_model_without_price_returns_none(self):
        stats = self._make_stats(model="gpt-4o")
        stats.add_real_usage(1_000_000, 1_000_000, 0)
        with patch(
            "RxyCode.RxyCode1_1_0.utils.streaming.load_config",
            return_value={"pricing": {"other-model": {"input": 1.0, "output": 2.0}}},
        ):
            assert stats.billing_amount is None

    def test_configured_price_calculates_cost(self):
        stats = self._make_stats(model="deepseek-chat")
        stats.add_real_usage(1_000_000, 500_000, 0)
        with patch(
            "RxyCode.RxyCode1_1_0.utils.streaming.load_config",
            return_value={
                "pricing": {"deepseek-chat": {"input": 2.0, "output": 8.0}},
            },
        ):
            # 1M input * $2/M + 0.5M output * $8/M = 2 + 4 = 6
            assert stats.billing_amount == pytest.approx(6.0)

    def test_partial_price_missing_output_treated_as_zero(self):
        stats = self._make_stats(model="m")
        stats.add_real_usage(1_000_000, 1_000_000, 0)
        with patch(
            "RxyCode.RxyCode1_1_0.utils.streaming.load_config",
            return_value={"pricing": {"m": {"input": 1.0}}},
        ):
            assert stats.billing_amount == pytest.approx(1.0)

    def test_set_model_updates_active_model(self):
        stats = self._make_stats()
        stats.set_model("gpt-4o-mini")
        assert stats._model_name == "gpt-4o-mini"

    def test_config_read_failure_returns_none(self):
        stats = self._make_stats(model="m")
        stats.add_real_usage(1000, 1000, 0)
        with patch(
            "RxyCode.RxyCode1_1_0.utils.streaming.load_config",
            side_effect=RuntimeError("io error"),
        ):
            assert stats.billing_amount is None
