"""B8 · `@` mention trigger and unified agent/invoke entry tests."""

from __future__ import annotations

import asyncio
import pytest

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    ChildStatus,
    TaskRequest,
    TriggerKind,
)
from RxyCode.RxyCode1_1_0.core.subagents.definitions import AgentDefinitionRegistry
from RxyCode.RxyCode1_1_0.core.subagents.manager import (
    AgentNotFoundError,
    ChildSessionManager,
    FeatureDisabledError,
    ModeMismatchError,
)
from RxyCode.RxyCode1_1_0.core.subagents.modes import SubagentConfig, SubagentFeatureFlags
from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import (
    get_manager,
    init_manager,
    reset_manager,
)
from RxyCode.RxyCode1_1_0.tools.agent_invoke import (
    ParsedMention,
    invoke_mention,
    invoke_mention_async,
    list_mentionable_agents,
    parse_mention,
)


# ============================================================================
# Mention parsing
# ============================================================================

class TestMentionParsing:
    """Parse @agent input lines."""

    def test_simple_mention(self):
        result = parse_mention("@explore 查找认证模块")
        assert result.matched is True
        assert result.agent_id == "explore"
        assert result.prompt == "查找认证模块"

    def test_mention_without_prompt(self):
        result = parse_mention("@explore")
        assert result.matched is True
        assert result.agent_id == "explore"
        assert result.prompt == ""

    def test_no_mention(self):
        result = parse_mention("explore 查找认证模块")
        assert result.matched is False
        assert result.agent_id == ""

    def test_empty_input(self):
        result = parse_mention("")
        assert result.matched is False
        assert result.agent_id == ""

    def test_whitespace_only(self):
        result = parse_mention("   ")
        assert result.matched is False

    def test_uppercase_agent_rejected(self):
        """Agent ids must be lowercase (invalid mention is not matched)."""
        result = parse_mention("@Explore 查找")
        assert result.matched is False

    def test_mention_with_hyphen_and_underscore(self):
        result = parse_mention("@code-reviewer 审查 diff")
        assert result.agent_id == "code-reviewer"
        result2 = parse_mention("@test_agent 运行测试")
        assert result2.agent_id == "test_agent"

    def test_multiline_prompt(self):
        result = parse_mention("@explore 第一行\n第二行")
        assert result.agent_id == "explore"
        assert "第一行" in result.prompt
        assert "第二行" in result.prompt

    def test_is_valid_property(self):
        assert ParsedMention(agent_id="explore", prompt="x", matched=True).is_valid
        assert not ParsedMention(agent_id="", prompt="x", matched=False).is_valid


# ============================================================================
# Mentionable agent listing
# ============================================================================

class TestMentionableAgents:
    """@ autocomplete must respect mode and hidden flags."""

    @pytest.fixture
    def registry(self):
        reg = AgentDefinitionRegistry()
        reg.register_builtin(AgentDefinition(id="explore", description="探索", mode=AgentMode.SUBAGENT))
        reg.register_builtin(AgentDefinition(id="general", description="通用", mode=AgentMode.SUBAGENT))
        reg.register_builtin(AgentDefinition(
            id="hidden_agent", description="隐藏", mode=AgentMode.SUBAGENT, hidden=True,
        ))
        reg.register_builtin(AgentDefinition(id="primary_only", description="主", mode=AgentMode.PRIMARY))
        reg.register_builtin(AgentDefinition(id="all_agent", description="全部", mode=AgentMode.ALL))
        return reg

    def test_list_only_subagent_and_all(self, registry):
        reset_manager()
        config = SubagentConfig(
            flags=SubagentFeatureFlags(subagents_enabled=True, subagents_mention=True),
        )
        init_manager(registry=registry, config=config)

        agents = list_mentionable_agents()
        ids = {a["id"] for a in agents}

        assert "explore" in ids
        assert "general" in ids
        assert "all_agent" in ids
        assert "hidden_agent" not in ids
        assert "primary_only" not in ids
        reset_manager()

    def test_agent_entry_shape(self, registry):
        reset_manager()
        init_manager(registry=registry, config=SubagentConfig())
        agents = list_mentionable_agents()
        if agents:
            entry = agents[0]
            assert "id" in entry
            assert "description" in entry
            assert "mode" in entry
        reset_manager()


# ============================================================================
# Mention dispatch
# ============================================================================

@pytest.fixture
def mention_manager():
    """A manager with all features enabled and mentionable agents."""
    reg = AgentDefinitionRegistry()
    reg.register_builtin(AgentDefinition(
        id="explore",
        description="探索",
        mode=AgentMode.SUBAGENT,
    ))
    reg.register_builtin(AgentDefinition(
        id="reviewer",
        description="审查",
        mode=AgentMode.SUBAGENT,
        hidden=False,
    ))
    config = SubagentConfig(
        flags=SubagentFeatureFlags(
            subagents_enabled=True,
            subagents_mention=True,
            subagents_task=True,
        )
    )
    manager = ChildSessionManager(registry=reg, config=config)
    reset_manager()
    init_manager(manager=manager)
    yield manager
    reset_manager()


class TestMentionDispatch:
    """invoke_mention dispatches to the manager correctly."""

    def test_invoke_valid_mention(self, mention_manager):
        result = asyncio.run(invoke_mention("explore", "查找认证模块"))
        assert result.child_session_id != ""
        assert result.status in (ChildStatus.COMPLETED, ChildStatus.FAILED)

    def test_invoke_unknown_agent(self, mention_manager):
        with pytest.raises(AgentNotFoundError):
            asyncio.run(invoke_mention("nonexistent", "查找"))

    def test_invoke_primary_only_agent_rejected(self, mention_manager):
        # Register a primary-only agent
        mention_manager.registry.register_builtin(AgentDefinition(
            id="main", description="主", mode=AgentMode.PRIMARY,
        ))
        with pytest.raises(ModeMismatchError, match="not mentionable"):
            asyncio.run(invoke_mention("main", "测试"))

    def test_dispatch_uses_mention_trigger(self, mention_manager):
        """The dispatched request must carry trigger=mention."""
        captured = {}
        original = mention_manager.dispatch

        async def _dispatch(req: TaskRequest):
            captured["trigger"] = req.trigger
            return await original(req)  # call the REAL dispatch

        mention_manager.dispatch = _dispatch
        try:
            asyncio.run(invoke_mention("explore", "查找"))
        finally:
            mention_manager.dispatch = original

        assert captured.get("trigger") == TriggerKind.MENTION

    def test_async_and_sync_entries(self, mention_manager):
        result = asyncio.run(invoke_mention_async("explore", "查找"))
        assert result.child_session_id != ""

        # Sync entry works without an event loop running
        from RxyCode.RxyCode1_1_0.tools.agent_invoke import invoke_mention_sync
        result2 = invoke_mention_sync("explore", "查找")
        assert result2.child_session_id != ""

    def test_feature_disabled_raises(self):
        """When mention feature is off, dispatch fails cleanly."""
        reg = AgentDefinitionRegistry()
        reg.register_builtin(AgentDefinition(id="explore", description="探索", mode=AgentMode.SUBAGENT))
        config = SubagentConfig(
            flags=SubagentFeatureFlags(
                subagents_enabled=True,
                subagents_mention=False,  # OFF
            )
        )
        reset_manager()
        init_manager(registry=reg, config=config)
        try:
            with pytest.raises(FeatureDisabledError, match="mention"):
                asyncio.run(invoke_mention("explore", "查找"))
        finally:
            reset_manager()

    def test_create_child_session_not_local(self, mention_manager):
        """invoke_mention must NOT create sessions locally — only via manager."""
        import inspect
        src = inspect.getsource(invoke_mention)
        assert "dispatch" in src  # delegates to manager
        assert "create_child_session" not in src
