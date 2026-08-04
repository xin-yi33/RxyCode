"""A7 wiring: context limits and tokenizer specs follow ModelCapabilities."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from RxyCode.RxyCode1_1_0.config.model_capabilities import (
    ModelCapabilities,
    resolve_graph_context_token_limit,
)
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, _estimate_tokens


class TestGraphContextTokenLimit:
    def test_follows_capabilities_when_config_none(self):
        caps = ModelCapabilities(context_window=32_000, compaction_threshold=28_800)
        limit = resolve_graph_context_token_limit({"context": {}}, caps)
        assert limit == 28_800

    def test_explicit_config_overrides_capabilities(self):
        caps = ModelCapabilities(compaction_threshold=28_800)
        limit = resolve_graph_context_token_limit(
            {"context": {"graph_context_token_limit": 50_000}},
            caps,
        )
        assert limit == 50_000

    def test_route_next_uses_capabilities_from_state(self, monkeypatch):
        from RxyCode.RxyCode1_1_0.core.graph import route_next
        from tests.test_core.test_route_next_token_estimate import _make_state

        caps = ModelCapabilities(compaction_threshold=28_800)
        big = "x" * (28_801 * 3)
        state = _make_state(memory_ctx=big)
        state["_capabilities"] = caps

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.config.settings.load_config",
            lambda: {"context": {"graph_context_token_limit": None}},
        )

        assert route_next(state) == "compress"


class TestTokenizerWiring:
    def test_module_estimate_differs_by_spec(self):
        text = "hello world " * 20
        tight = _estimate_tokens(text, "chars:2.0")
        loose = _estimate_tokens(text, "chars:8.0")
        assert tight > loose

    def test_agent_estimate_tokens_uses_capabilities(self, monkeypatch):
        monkeypatch.setattr(
            AgentV2,
            "__init__",
            lambda self, model_name=None: None,
        )
        agent = AgentV2.__new__(AgentV2)
        agent._capabilities = replace(
            ModelCapabilities(),
            tokenizer="chars:2.0",
        )
        messages = [SimpleNamespace(content="abcd" * 10)]
        tight = agent._estimate_tokens(messages)

        agent._capabilities = replace(
            ModelCapabilities(),
            tokenizer="chars:8.0",
        )
        loose = agent._estimate_tokens(messages)
        assert tight > loose
