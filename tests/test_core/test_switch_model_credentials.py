"""Regression tests for empty-credential model switching."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_llm_kwargs_rejects_empty_api_key():
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.providers.base import BaseProvider

    class _P(BaseProvider):
        name = "test"

        def matches(self, base_url: str, model_name: str) -> bool:
            return True

        def capabilities(self, model_config: dict):
            return DEFAULT_CAPABILITIES

    with pytest.raises(ValueError, match="non-empty api_key"):
        _P().llm_kwargs(
            {
                "model_name": "deepseek-v4-flash-free",
                "api_key": "",
                "base_url": "https://opencode.ai/zen/v1",
                "resolved_max_tokens": 1024,
            },
            DEFAULT_CAPABILITIES,
        )


def test_switch_model_rejects_empty_credential_without_mutating_llm(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._active_task = None
    agent._cfg = {}
    agent._memory = SimpleNamespace(save_session=lambda: None)
    previous_llm = object()
    previous_config = {"model_name": "keep-me", "api_key": "sk-old"}
    agent._llm = previous_llm
    agent.model_config = previous_config

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.agent_v2._settings.get_model_config",
        lambda name, cfg: {
            "model_name": "deepseek-v4-flash-free",
            "api_key": "",
            "api_key_env": "OPENCODE_ZEN_API_KEY",
            "base_url": "https://opencode.ai/zen/v1",
        },
    )

    with pytest.raises(ValueError, match="API credential is unavailable"):
        agent.switch_model("zen/deepseek-v4-flash-free")

    assert agent._llm is previous_llm
    assert agent.model_config is previous_config


def test_switch_model_reads_models_added_after_startup(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import agent_v2 as mod

    agent = mod.AgentV2.__new__(mod.AgentV2)
    agent._active_task = None
    agent._session_id = "sess-1"
    agent._cfg = {
        "models": {
            "old/model": {
                "model_name": "old-model",
                "api_key": "sk-old",
                "base_url": "https://old.example/v1",
            }
        },
        "active_model": "old/model",
        "mcpServers": {"kept": {"command": "stay"}},
    }
    previous_llm = object()
    previous_memory = SimpleNamespace(save_session=lambda: None, bind_rag_indexer=lambda *_a, **_k: None)
    agent._llm = previous_llm
    agent.model_config = {"model_name": "old-model", "api_key": "sk-old"}
    agent._memory = previous_memory
    agent._model_router = SimpleNamespace(register=MagicMock())
    agent._session_loaded = True
    agent._sync_token_stats_context = lambda: None
    agent._provider_name = lambda _cfg: "p"
    fresh = {
        "models": {
            **agent._cfg["models"],
            "new/model": {
                "model_name": "new-model",
                "api_key": "sk-new",
                "base_url": "https://new.example/v1",
            },
        },
        "active_model": "new/model",
    }
    monkeypatch.setattr(mod._settings, "load_config", lambda: fresh)

    def _build(cfg):
        if cfg.get("api_key") == "explode":
            raise RuntimeError("build failed")
        return {"llm": cfg["model_name"]}

    agent._build_llm_from_config = _build
    monkeypatch.setattr(mod.providers, "resolve", lambda _cfg: SimpleNamespace(capabilities=lambda _c: SimpleNamespace()))
    monkeypatch.setattr(mod.token_stats, "set_model", lambda *_a, **_k: None)

    class _Memory:
        def __init__(self, session_id, llm):
            self.session_id = session_id
            self.llm = llm

        def bind_rag_indexer(self, _indexer):
            return None

    monkeypatch.setattr(mod, "MemoryManager", _Memory)

    switched = agent.switch_model("new/model")
    assert switched["model_name"] == "new-model"
    assert agent._llm == {"llm": "new-model"}
    assert agent.model_config["model_name"] == "new-model"
    assert agent._cfg["mcpServers"] == {"kept": {"command": "stay"}}
    assert agent._cfg["active_model"] == "old/model"
    assert "new/model" in agent._cfg["models"]

    agent._build_llm_from_config = lambda _cfg: (_ for _ in ()).throw(RuntimeError("build failed"))
    live_llm = agent._llm
    live_memory = agent._memory
    with pytest.raises(RuntimeError, match="build failed"):
        agent.switch_model("new/model")
    assert agent._llm is live_llm
    assert agent._memory is live_memory
    assert agent.model_config["model_name"] == "new-model"
