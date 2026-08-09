"""B2 · AgentDefinition validation and config loader tests."""

from __future__ import annotations

import json
import pytest

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    PermissionSpec,
    PermissionVerdict,
    TaskPermissionSpec,
    WorkspaceMode,
)
from core.subagents.definitions import (
    AgentDefinitionRegistry,
    DefinitionError,
    validate_agent_definition,
    RESERVED_IDS,
)
from core.subagents.config_loader import (
    ConfigLoadError,
    load_agent_from_json,
    load_agent_from_markdown,
    load_agent_from_yaml,
    normalize_raw_config,
)


# ============================================================================
# ID validation
# ============================================================================

class TestIdValidation:
    """Agent id naming rules and uniqueness."""

    def test_missing_id_rejected(self):
        with pytest.raises(DefinitionError, match="id is required"):
            validate_agent_definition({"description": "test"})

    def test_empty_id_rejected(self):
        with pytest.raises(DefinitionError, match="id is required"):
            validate_agent_definition({"id": "", "description": "test"})

    def test_id_must_start_with_lowercase(self):
        with pytest.raises(DefinitionError, match="Agent id"):
            validate_agent_definition({"id": "Explore", "description": "test"})

    def test_id_cannot_start_with_number(self):
        with pytest.raises(DefinitionError, match="Agent id"):
            validate_agent_definition({"id": "2explore", "description": "test"})

    def test_id_max_64_chars(self):
        long_id = "a" * 65
        with pytest.raises(DefinitionError, match="Agent id"):
            validate_agent_definition({"id": long_id, "description": "test"})

    def test_valid_ids_accepted(self):
        valid = ["explore", "code-reviewer", "test_agent", "a1", "my-agent-2"]
        for agent_id in valid:
            result = validate_agent_definition({"id": agent_id, "description": "test"})
            assert result.id == agent_id

    def test_reserved_ids_rejected(self):
        for reserved in RESERVED_IDS:
            with pytest.raises(DefinitionError, match="reserved"):
                validate_agent_definition({"id": reserved, "description": "test"})


# ============================================================================
# Mode validation
# ============================================================================

class TestModeValidation:
    """Agent mode must be primary, subagent, or all."""

    def test_default_mode_is_subagent(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.mode == AgentMode.SUBAGENT

    def test_invalid_mode_rejected(self):
        with pytest.raises(DefinitionError, match="Invalid mode"):
            validate_agent_definition({"id": "test", "description": "test", "mode": "super"})

    def test_all_three_modes_accepted(self):
        for mode in ("primary", "subagent", "all"):
            result = validate_agent_definition({"id": "test", "description": "test", "mode": mode})
            assert result.mode == AgentMode(mode)


# ============================================================================
# Steps validation
# ============================================================================

class TestStepsValidation:
    """Steps must be a positive integer or None."""

    def test_negative_steps_rejected(self):
        with pytest.raises(DefinitionError, match="steps"):
            validate_agent_definition({"id": "test", "description": "test", "steps": -1})

    def test_zero_steps_rejected(self):
        with pytest.raises(DefinitionError, match="steps"):
            validate_agent_definition({"id": "test", "description": "test", "steps": 0})

    def test_non_integer_steps_rejected(self):
        with pytest.raises(DefinitionError, match="steps"):
            validate_agent_definition({"id": "test", "description": "test", "steps": "many"})

    def test_null_steps_accepted(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.steps is None

    def test_positive_steps_accepted(self):
        result = validate_agent_definition({"id": "test", "description": "test", "steps": 12})
        assert result.steps == 12


# ============================================================================
# subagent_depth validation
# ============================================================================

class TestSubagentDepthValidation:
    """subagent_depth must be a non-negative integer."""

    def test_default_depth_is_1(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.subagent_depth == 1

    def test_negative_depth_rejected(self):
        with pytest.raises(DefinitionError, match="subagent_depth"):
            validate_agent_definition({"id": "test", "description": "test", "subagent_depth": -1})

    def test_depth_zero_accepted(self):
        result = validate_agent_definition({"id": "test", "description": "test", "subagent_depth": 0})
        assert result.subagent_depth == 0
        assert not result.can_create_children

    def test_depth_two_accepted(self):
        result = validate_agent_definition({"id": "test", "description": "test", "subagent_depth": 2})
        assert result.subagent_depth == 2


# ============================================================================
# workspace_scope validation
# ============================================================================

class TestWorkspaceScopeValidation:
    """workspace_scope must be a valid WorkspaceMode."""

    def test_default_is_read_only(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.workspace_scope == WorkspaceMode.READ_ONLY

    def test_invalid_scope_rejected(self):
        with pytest.raises(DefinitionError, match="workspace_scope"):
            validate_agent_definition({"id": "test", "description": "test", "workspace_scope": "unlimited"})

    def test_all_three_scopes_accepted(self):
        for scope in ("read_only", "leased_write", "isolated_worktree"):
            result = validate_agent_definition({"id": "test", "description": "test", "workspace_scope": scope})
            assert result.workspace_scope == WorkspaceMode(scope)


# ============================================================================
# Permission validation
# ============================================================================

class TestPermissionValidation:
    """PermissionSpec parsing and validation."""

    def test_default_permission_all_deny(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.permission.external_directory == PermissionVerdict.DENY

    def test_string_shorthand(self):
        """Permission 'read: allow' as string → catch-all rule."""
        raw = {
            "id": "test", "description": "test",
            "permission": {"read": "allow", "edit": "deny"}
        }
        result = validate_agent_definition(raw)
        assert result.permission.read.rules[0].verdict == PermissionVerdict.ALLOW
        assert result.permission.edit.rules[0].verdict == PermissionVerdict.DENY

    def test_dict_permission_with_patterns(self):
        """Dict permission with glob patterns."""
        raw = {
            "id": "test", "description": "test",
            "permission": {
                "read": {"src/**": "allow", "**/*.secret": "deny"},
                "task": {"explore": "allow", "general": "deny"},
            }
        }
        result = validate_agent_definition(raw)
        assert len(result.permission.read.rules) == 2
        assert result.permission.read.rules[0].pattern == "src/**"
        assert result.permission.read.rules[0].verdict == PermissionVerdict.ALLOW

    def test_external_directory_default_deny(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.permission.external_directory == PermissionVerdict.DENY

    def test_external_directory_allow(self):
        raw = {
            "id": "test", "description": "test",
            "permission": {"external_directory": "allow"}
        }
        result = validate_agent_definition(raw)
        assert result.permission.external_directory == PermissionVerdict.ALLOW


# ============================================================================
# task_permission — must come from permission.task, NOT top-level
# ============================================================================

class TestTaskPermission:
    """Top-level task_permission must be rejected; only permission.task allowed."""

    def test_top_level_task_permission_rejected(self):
        raw = {
            "id": "test", "description": "test",
            "task_permission": {"explore": "allow"}
        }
        with pytest.raises(DefinitionError, match="task_permission"):
            validate_agent_definition(raw)

    def test_permission_dot_task_normalized(self):
        """permission.task is correctly normalized into TaskPermissionSpec."""
        raw = {
            "id": "test", "description": "test",
            "permission": {
                "task": {"explore": "allow", "general": "deny"}
            }
        }
        result = validate_agent_definition(raw)
        assert result.task_permission.allows("explore") is True
        assert result.task_permission.allows("general") is False
        assert result.task_permission.allows("unknown") is False  # default deny


# ============================================================================
# hidden flag
# ============================================================================

class TestHiddenFlag:
    """hidden only affects UI listing, not explicit Task invocation."""

    def test_default_not_hidden(self):
        result = validate_agent_definition({"id": "test", "description": "test"})
        assert result.hidden is False

    def test_hidden_agent_not_in_visible_list(self):
        reg = AgentDefinitionRegistry()
        hidden = validate_agent_definition({"id": "hidden1", "description": "h", "hidden": True, "mode": "subagent"})
        visible = validate_agent_definition({"id": "visible1", "description": "v", "mode": "subagent"})
        reg.register_user(hidden)
        reg.register_user(visible)
        visible_list = reg.list_visible()
        assert visible in visible_list
        assert hidden not in visible_list

    def test_hidden_agent_still_in_registry(self):
        """hidden agents can still be dispatched via explicit Task."""
        reg = AgentDefinitionRegistry()
        hidden = validate_agent_definition({"id": "hidden1", "description": "h", "hidden": True, "mode": "subagent"})
        reg.register_user(hidden)
        assert reg.get("hidden1") is not None


# ============================================================================
# Registry tests
# ============================================================================

class TestAgentDefinitionRegistry:
    """Registry behavior: registration, builtin protection, lookup."""

    def test_register_and_get(self):
        reg = AgentDefinitionRegistry()
        agent = validate_agent_definition({"id": "explore", "description": "code explorer"})
        reg.register_user(agent)
        assert reg.get("explore") is agent

    def test_builtin_cannot_be_overridden(self):
        reg = AgentDefinitionRegistry()
        builtin = validate_agent_definition({"id": "explore", "description": "built-in explorer"})
        reg.register_builtin(builtin)

        user = validate_agent_definition({"id": "explore", "description": "user override"})
        with pytest.raises(DefinitionError, match="Cannot override built-in"):
            reg.register_user(user)

    def test_user_duplicate_allowed(self):
        """Later user def replaces earlier user def (non-builtin)."""
        reg = AgentDefinitionRegistry()
        a1 = validate_agent_definition({"id": "explore", "description": "v1"})
        a2 = validate_agent_definition({"id": "explore", "description": "v2"})
        reg.register_user(a1)
        reg.register_user(a2)  # Overwrites a1
        assert reg.get("explore").description == "v2"

    def test_list_visible_filters_mode_and_hidden(self):
        reg = AgentDefinitionRegistry()
        primary = validate_agent_definition({"id": "main", "description": "p", "mode": "primary"})
        sub = validate_agent_definition({"id": "sub1", "description": "s", "mode": "subagent"})
        hidden_sub = validate_agent_definition({"id": "sub2", "description": "hs", "mode": "subagent", "hidden": True})
        all_mode = validate_agent_definition({"id": "all1", "description": "a", "mode": "all"})

        for a in (primary, sub, hidden_sub, all_mode):
            reg.register_user(a)

        visible = reg.list_visible()
        visible_ids = {a.id for a in visible}
        assert "main" not in visible_ids       # primary only
        assert "sub1" in visible_ids           # subagent, not hidden
        assert "sub2" not in visible_ids       # hidden
        assert "all1" in visible_ids           # all mode

    def test_list_all_returns_all(self):
        reg = AgentDefinitionRegistry()
        for i in range(3):
            agent = validate_agent_definition({"id": f"a{i}", "description": f"agent {i}"})
            reg.register_user(agent)
        assert len(list(reg)) == 3


# ============================================================================
# JSON / Markdown / YAML loader tests
# ============================================================================

class TestJsonLoader:
    """JSON agent definition loading."""

    def test_valid_json(self):
        data = json.dumps({"id": "explore", "description": "test", "mode": "subagent"})
        result = load_agent_from_json(data)
        assert result["id"] == "explore"

    def test_invalid_json_raises(self):
        with pytest.raises(ConfigLoadError, match="Invalid JSON"):
            load_agent_from_json("{not json}")

    def test_non_object_raises(self):
        with pytest.raises(ConfigLoadError, match="JSON object"):
            load_agent_from_json("[1, 2, 3]")


class TestYamlLoader:
    """YAML agent definition loading."""

    def test_valid_yaml(self):
        data = "id: explore\ndescription: test\n"
        result = load_agent_from_yaml(data)
        assert result["id"] == "explore"

    def test_non_mapping_raises(self):
        with pytest.raises(ConfigLoadError, match="mapping"):
            load_agent_from_yaml("- item1\n- item2\n")


class TestMarkdownLoader:
    """Markdown frontmatter agent definition loading."""

    def test_valid_markdown(self):
        data = (
            "---\n"
            "id: explore\n"
            "description: code explorer\n"
            "mode: subagent\n"
            "---\n"
            "You are a read-only code exploration agent.\n"
        )
        result = load_agent_from_markdown(data)
        assert result["id"] == "explore"
        assert "You are a read-only code exploration agent" in result["prompt"]

    def test_markdown_body_becomes_prompt(self):
        data = (
            "---\n"
            "id: test\n"
            "description: test agent\n"
            "---\n"
            "System prompt body here.\n"
        )
        result = load_agent_from_markdown(data)
        assert result["prompt"] == "System prompt body here."

    def test_frontmatter_prompt_overrides_body(self):
        data = (
            "---\n"
            "id: test\n"
            "description: test agent\n"
            "prompt: explicit prompt\n"
            "---\n"
            "Body that should be ignored.\n"
        )
        result = load_agent_from_markdown(data)
        assert result["prompt"] == "explicit prompt"

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ConfigLoadError, match="frontmatter"):
            load_agent_from_markdown("Just some markdown\n\nNo frontmatter here.\n")


# ============================================================================
# JSON / Markdown equivalence
# ============================================================================

class TestFormatEquivalence:
    """JSON and Markdown must produce identical validated AgentDefinitions."""

    JSON_DEF = {
        "id": "explore",
        "description": "只读代码探索",
        "mode": "subagent",
        "steps": 12,
        "permission": {
            "read": {"**": "allow"},
            "edit": {"**": "deny"},
            "bash": {"pytest *": "allow", "**": "deny"},
            "task": {"**": "deny"},
            "external_directory": "deny",
        },
        "hidden": False,
        "subagent_depth": 1,
        "workspace_scope": "read_only",
    }

    MARKDOWN_DEF = (
        "---\n"
        "id: explore\n"
        "description: 只读代码探索\n"
        "mode: subagent\n"
        "steps: 12\n"
        "permission:\n"
        "  read:\n"
        "    '**': allow\n"
        "  edit:\n"
        "    '**': deny\n"
        "  bash:\n"
        "    'pytest *': allow\n"
        "    '**': deny\n"
        "  task:\n"
        "    '**': deny\n"
        "  external_directory: deny\n"
        "hidden: false\n"
        "subagent_depth: 1\n"
        "workspace_scope: read_only\n"
        "---\n"
        "你是只读探索 Agent。只返回证据，不修改文件。\n"
    )

    def test_json_and_markdown_produce_same_definition(self):
        """JSON and Markdown loading must yield equivalent AgentDefinitions."""
        json_normalized = normalize_raw_config(self.JSON_DEF)
        json_agent = validate_agent_definition(json_normalized)

        md_raw = load_agent_from_markdown(self.MARKDOWN_DEF)
        md_normalized = normalize_raw_config(md_raw)
        md_agent = validate_agent_definition(md_normalized)

        # Core identity fields match
        assert json_agent.id == md_agent.id
        assert json_agent.description == md_agent.description
        assert json_agent.mode == md_agent.mode
        assert json_agent.steps == md_agent.steps
        assert json_agent.subagent_depth == md_agent.subagent_depth
        assert json_agent.workspace_scope == md_agent.workspace_scope
        assert json_agent.hidden == md_agent.hidden

        # Permissions match
        assert json_agent.permission.external_directory == md_agent.permission.external_directory
        assert len(json_agent.permission.read.rules) == len(md_agent.permission.read.rules)

        # Markdown has the body as prompt
        assert "只读探索 Agent" in (md_agent.prompt or "")


# ============================================================================
# Normalize raw config edge cases
# ============================================================================

class TestNormalizeRawConfig:
    """Edge cases in config normalization."""

    def test_permission_string_shorthand_expanded(self):
        raw = {"id": "test", "description": "test", "permission": "deny"}
        normalized = normalize_raw_config(raw)
        assert normalized["permission"]["read"] == "deny"
        assert normalized["permission"]["edit"] == "deny"
        assert normalized["permission"]["bash"] == "deny"

    def test_task_permission_passed_through_for_rejection(self):
        """Top-level task_permission must survive normalization so validator can reject it."""
        raw = {"id": "test", "description": "test", "task_permission": {"explore": "allow"}}
        normalized = normalize_raw_config(raw)
        assert "task_permission" in normalized

    def test_description_required(self):
        with pytest.raises(DefinitionError, match="description"):
            validate_agent_definition({"id": "test"})

    def test_description_whitespace_only_rejected(self):
        with pytest.raises(DefinitionError, match="description"):
            validate_agent_definition({"id": "test", "description": "   "})


# ============================================================================
# AgentDefinition derived properties
# ============================================================================

class TestAgentDefinitionProperties:
    """Derived properties on AgentDefinition."""

    def test_primary_is_primary_capable(self):
        agent = validate_agent_definition({"id": "main", "description": "p", "mode": "primary"})
        assert agent.is_primary_capable is True
        assert agent.is_subagent_capable is False

    def test_subagent_is_subagent_capable(self):
        agent = validate_agent_definition({"id": "sub", "description": "s", "mode": "subagent"})
        assert agent.is_subagent_capable is True
        assert agent.is_primary_capable is False

    def test_all_is_both_capable(self):
        agent = validate_agent_definition({"id": "flex", "description": "f", "mode": "all"})
        assert agent.is_primary_capable is True
        assert agent.is_subagent_capable is True

    def test_depth_zero_cannot_create_children(self):
        agent = validate_agent_definition({"id": "leaf", "description": "l", "subagent_depth": 0})
        assert agent.can_create_children is False

    def test_subagent_mode_cannot_create_children(self):
        """Subagents cannot create children even with depth>0 (they're not primary-capable)."""
        agent = validate_agent_definition({"id": "sub", "description": "s", "mode": "subagent", "subagent_depth": 2})
        assert agent.can_create_children is False


# ============================================================================
# TaskPermissionSpec behavior
# ============================================================================

class TestTaskPermissionSpecBehavior:
    """TaskPermissionSpec access control logic."""

    def test_empty_spec_denies_all(self):
        spec = TaskPermissionSpec()
        assert spec.allows("explore") is False
        assert spec.allows("anything") is False

    def test_default_allow_spec(self):
        spec = TaskPermissionSpec(default_verdict=PermissionVerdict.ALLOW)
        assert spec.allows("anything") is True

    def test_explicit_allow_overrides_default_deny(self):
        spec = TaskPermissionSpec(
            allowed_agents=("explore",),
            default_verdict=PermissionVerdict.DENY,
        )
        assert spec.allows("explore") is True
        assert spec.allows("general") is False

    def test_explicit_deny_overrides_default_allow(self):
        spec = TaskPermissionSpec(
            denied_agents=("dangerous",),
            default_verdict=PermissionVerdict.ALLOW,
        )
        assert spec.allows("safe") is True
        assert spec.allows("dangerous") is False

    def test_from_string_raw(self):
        spec = TaskPermissionSpec.from_raw("deny")
        assert spec.allows("anything") is False

        spec2 = TaskPermissionSpec.from_raw("allow")
        assert spec2.allows("anything") is True
