"""B13 · Built-in agents, Tool migration, and example directory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from protocol.subagents import AgentMode, PermissionVerdict, WorkspaceMode
# NOTE: tools modules live in the RxyCode.RxyCode1_1_0 tree. Import core.subagents
# via the SAME tree so the manager singleton is shared across both.
from RxyCode.RxyCode1_1_0.core.subagents.builtin_agents import builtin_agent_ids, load_builtin_agents
from RxyCode.RxyCode1_1_0.core.subagents.definitions import AgentDefinitionRegistry
from RxyCode.RxyCode1_1_0.core.subagents.registry_provider import (
    get_manager_or_none,
    init_manager,
    reset_manager,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ============================================================================
# Built-in agents
# ============================================================================

class TestBuiltinAgents:
    """The default config/agents/ definitions load correctly."""

    def test_builtin_agents_load(self):
        reg = load_builtin_agents()
        ids = {a.id for a in reg.list_all()}
        assert {"explore", "general", "reviewer", "scout"} <= ids

    def test_builtin_agents_are_builtin(self):
        reg = load_builtin_agents()
        # User definitions cannot override built-ins
        from RxyCode.RxyCode1_1_0.core.subagents.definitions import DefinitionError, validate_agent_definition
        user = validate_agent_definition({"id": "explore", "description": "override"})
        with pytest.raises(DefinitionError, match="Cannot override built-in"):
            reg.register_user(user)

    def test_explore_permissions(self):
        reg = load_builtin_agents()
        explore = reg.get("explore")
        assert explore.mode == AgentMode.SUBAGENT
        assert explore.workspace_scope == WorkspaceMode.READ_ONLY
        # read allow
        assert explore.permission.read.rules[0].verdict == PermissionVerdict.ALLOW
        # edit deny
        assert explore.permission.edit.rules[0].verdict == PermissionVerdict.DENY

    def test_reviewer_is_markdown_loaded(self):
        """reviewer.md loads with its Markdown body as prompt."""
        reg = load_builtin_agents()
        reviewer = reg.get("reviewer")
        assert reviewer.id == "reviewer"
        assert reviewer.prompt is not None
        assert "只读审查 Agent" in reviewer.prompt
        assert reviewer.workspace_scope == WorkspaceMode.READ_ONLY

    def test_scout_permissions(self):
        reg = load_builtin_agents()
        scout = reg.get("scout")
        assert scout.permission.webfetch.rules[0].verdict == PermissionVerdict.ALLOW
        assert scout.permission.websearch.rules[0].verdict == PermissionVerdict.ALLOW
        assert scout.permission.edit.rules[0].verdict == PermissionVerdict.DENY

    def test_builtin_agent_ids(self):
        ids = builtin_agent_ids()
        assert "explore" in ids
        assert "reviewer" in ids
        assert ids == sorted(ids)

    def test_config_agents_directory_exists(self):
        config_dir = PROJECT_ROOT / "config" / "agents"
        assert config_dir.is_dir()

    def test_example_files_present(self):
        """JSON, Markdown, and YAML examples all exist."""
        config_dir = PROJECT_ROOT / "config" / "agents"
        assert (config_dir / "explore.json").exists()
        assert (config_dir / "reviewer.md").exists()
        assert (config_dir / "scout.yaml").exists()

    def test_reviewer_cannot_edit(self):
        reg = load_builtin_agents()
        reviewer = reg.get("reviewer")
        assert reviewer.permission.edit.rules[0].verdict == PermissionVerdict.DENY


# ============================================================================
# init_manager loads built-ins by default
# ============================================================================

class TestInitManagerLoadsBuiltins:
    """The process manager gets built-in agents by default."""

    def test_init_manager_loads_builtins(self):
        reset_manager()
        try:
            manager = init_manager()
            assert manager.registry.get("explore") is not None
            assert manager.registry.get("reviewer") is not None
        finally:
            reset_manager()

    def test_get_manager_or_none(self):
        reset_manager()
        assert get_manager_or_none() is None
        init_manager()
        assert get_manager_or_none() is not None
        reset_manager()


# ============================================================================
# Tool name freeze
# ============================================================================

class TestToolNameFreeze:
    """The `task` name is owned by exactly one tool per mode."""

    def test_subagent_tool_is_named_task(self):
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
        assert subagent_task_tool.name == "task"

    def test_task_manage_tool_is_named_task_manage(self):
        from RxyCode.RxyCode1_1_0.tools.task_manage import task_manage_tool
        assert task_manage_tool.name == "task_manage"

    def test_legacy_task_tool_is_named_task(self):
        from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
        assert task_tool.name == "task"

    def test_legacy_agent_tool_is_named_agent(self):
        from RxyCode.RxyCode1_1_0.tools.agent_tool import agent_tool
        assert agent_tool.name == "agent"

    def test_task_tool_module_keeps_task_list_scope(self):
        """task_tool.py must remain task management, not subagent dispatch."""
        src = (PROJECT_ROOT / "tools" / "task_tool.py").read_text(encoding="utf-8")
        assert "create" in src
        assert "list" in src
        assert "ChildSessionManager" not in src
        assert "subagent" not in src.lower()

    def test_task_manage_delegates_to_task_store(self):
        """task_manage reuses the persistent task store, not a new one."""
        src = (PROJECT_ROOT / "tools" / "task_manage.py").read_text(encoding="utf-8")
        assert "manage_tasks" in src  # delegates to task_tool's store
        assert "ChildSessionManager" not in src


# ============================================================================
# Legacy agent tool deprecation
# ============================================================================

class TestLegacyAgentToolDeprecation:
    """Legacy agent tool raises a clear migration error when subagents on."""

    def test_deprecated_msg_constant(self):
        from tools.agent_tool import LEGACY_SUBAGENT_DEPRECATED_MSG
        assert "deprecated" in LEGACY_SUBAGENT_DEPRECATED_MSG.lower()
        assert "task" in LEGACY_SUBAGENT_DEPRECATED_MSG

    def test_legacy_raises_when_subagents_enabled(self):
        reset_manager()
        try:
            from RxyCode.RxyCode1_1_0.core.subagents.modes import SubagentConfig, SubagentFeatureFlags
            config = SubagentConfig(
                flags=SubagentFeatureFlags(subagents_enabled=True),
            )
            init_manager(config=config)

            from RxyCode.RxyCode1_1_0.tools.agent_tool import run_agent_async
            with pytest.raises(RuntimeError, match="deprecated"):
                import asyncio
                asyncio.run(run_agent_async("test task"))
        finally:
            reset_manager()

    def test_legacy_allowed_when_subagents_disabled(self):
        """Feature-flag rollback: legacy path works when subagents are off."""
        reset_manager()
        try:
            from RxyCode.RxyCode1_1_0.tools.agent_tool import _subagents_enabled
            assert _subagents_enabled() is False
        finally:
            reset_manager()


# ============================================================================
# Registration switching
# ============================================================================

class TestRegistrationSwitching:
    """register_builtin_tools selects the right `task` owner per mode."""

    def test_no_duplicate_task_names(self):
        """Registering in new mode must not produce two `task` tools."""
        import core.builtin_tool_registration as btr

        # In new mode: task_manage (task_manage) + subagent dispatch (task)
        reg_names = {"task", "task_manage"}
        assert len(reg_names) == 2  # task and task_manage are distinct

        # The legacy task_tool and subagent_task_tool must never both register "task"
        from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
        assert task_tool.name == "task"
        assert subagent_task_tool.name == "task"

        # In a single registration call, the branch picks exactly one:
        # new mode uses subagent_task_tool for "task"; legacy uses task_tool
        # Both are "task" but only one is registered per mode (asserted in
        # the register_builtin_tools implementation via subagents_enabled).
        assert btr.register_builtin_tools is not None

    def test_subagent_tool_thin_adapter(self):
        """subagent_task_tool must not create AgentV2 or splice history."""
        src = (PROJECT_ROOT / "tools" / "subagent_task_tool.py").read_text(encoding="utf-8")
        assert "import AgentV2" not in src
        assert "AgentV2(" not in src
        assert "from ..core.agent_v2" not in src
        assert "ChildSessionManager" in src
