"""B3 · Primary/Subagent modes and default configuration tests."""

from __future__ import annotations

import pytest

from protocol.subagents import AgentMode
from core.subagents.modes import (
    SubagentConfig,
    SubagentFeatureFlags,
    SubagentCapability,
    SessionMode,
    SessionIdentity,
    build_capability,
    get_subagent_config,
    reset_subagent_config,
    set_subagent_config,
    validate_primary_entry,
    validate_subagent_entry,
)


# ============================================================================
# Feature flags — defaults
# ============================================================================

class TestFeatureFlagDefaults:
    """All feature flags must default to OFF — single-agent path zero regression."""

    def test_subagents_enabled_defaults_false(self):
        flags = SubagentFeatureFlags()
        assert flags.subagents_enabled is False

    def test_subagents_task_defaults_false(self):
        flags = SubagentFeatureFlags()
        assert flags.subagents_task is False

    def test_subagents_mention_defaults_false(self):
        flags = SubagentFeatureFlags()
        assert flags.subagents_mention is False

    def test_subagents_child_tasks_defaults_false(self):
        flags = SubagentFeatureFlags()
        assert flags.subagents_child_tasks is False

    def test_subagent_config_defaults_all_off(self):
        config = SubagentConfig()
        assert config.flags.subagents_enabled is False
        assert config.flags.subagents_task is False
        assert config.flags.subagents_mention is False
        assert config.flags.subagents_child_tasks is False

    def test_default_config_no_extra_model_calls(self):
        """Default config must not produce additional model invocations."""
        config = SubagentConfig()
        cap = config.capability
        assert cap.subagents_enabled is False
        assert cap.task is False
        assert cap.mention is False
        assert cap.child_tasks is False


# ============================================================================
# Capability reporting
# ============================================================================

class TestCapabilityReporting:
    """Capability discovery must report accurate availability."""

    def test_build_capability_all_off(self):
        flags = SubagentFeatureFlags()
        cap = build_capability(flags)
        assert cap.protocol_version == 1
        assert cap.subagents_enabled is False
        assert cap.task is False
        assert cap.mention is False
        assert cap.child_tasks is False

    def test_build_capability_task_only(self):
        flags = SubagentFeatureFlags(
            subagents_enabled=True,
            subagents_task=True,
        )
        cap = build_capability(flags)
        assert cap.subagents_enabled is True
        assert cap.task is True
        assert cap.mention is False
        assert cap.child_tasks is False

    def test_build_capability_all_on(self):
        flags = SubagentFeatureFlags(
            subagents_enabled=True,
            subagents_task=True,
            subagents_mention=True,
            subagents_child_tasks=True,
        )
        cap = build_capability(flags)
        assert cap.subagents_enabled is True
        assert cap.task is True
        assert cap.mention is True
        assert cap.child_tasks is True

    def test_capability_does_not_expose_internal_state(self):
        """Capability is a snapshot — mutating flags after doesn't change it."""
        flags = SubagentFeatureFlags(subagents_enabled=True)
        cap = build_capability(flags)
        flags.subagents_enabled = False
        assert cap.subagents_enabled is True  # Snapshot unaffected


# ============================================================================
# Session identity
# ============================================================================

class TestSessionIdentity:
    """SessionIdentity tracks agent mode and lineage."""

    def test_default_is_primary(self):
        identity = SessionIdentity()
        assert identity.session_mode == SessionMode.PRIMARY
        assert identity.agent_id == "primary"

    def test_child_session_identity(self):
        identity = SessionIdentity(
            session_mode=SessionMode.CHILD,
            agent_id="explore",
            parent_session_id="ses_primary_1",
            root_session_id="ses_primary_1",
        )
        assert identity.session_mode == SessionMode.CHILD
        assert identity.agent_id == "explore"
        assert identity.parent_session_id == "ses_primary_1"

    def test_primary_has_no_parent(self):
        identity = SessionIdentity()
        assert identity.parent_session_id == ""
        assert identity.root_session_id == ""


# ============================================================================
# Entry validation
# ============================================================================

class TestPrimaryEntryValidation:
    """Only primary and all modes can be user-facing primaries."""

    def test_primary_mode_accepted(self):
        validate_primary_entry(AgentMode.PRIMARY)  # Does not raise

    def test_all_mode_accepted(self):
        validate_primary_entry(AgentMode.ALL)  # Does not raise

    def test_subagent_mode_rejected(self):
        with pytest.raises(ValueError, match="cannot serve as a user-facing primary"):
            validate_primary_entry(AgentMode.SUBAGENT)


class TestSubagentEntryValidation:
    """Only subagent and all modes can be dispatched as children."""

    def test_subagent_mode_accepted(self):
        validate_subagent_entry(AgentMode.SUBAGENT)  # Does not raise

    def test_all_mode_accepted(self):
        validate_subagent_entry(AgentMode.ALL)  # Does not raise

    def test_primary_mode_rejected_for_normal_task(self):
        with pytest.raises(ValueError, match="cannot be dispatched as a child"):
            validate_subagent_entry(AgentMode.PRIMARY)

    def test_primary_mode_accepted_for_subtask_command(self):
        """subtask=true exception: primary agents can be forced into child."""
        validate_subagent_entry(AgentMode.PRIMARY, is_subtask_command=True)  # Does not raise

    def test_subagent_mode_accepted_for_subtask(self):
        validate_subagent_entry(AgentMode.SUBAGENT, is_subtask_command=True)  # Does not raise

    def test_all_mode_accepted_for_subtask(self):
        validate_subagent_entry(AgentMode.ALL, is_subtask_command=True)  # Does not raise


# ============================================================================
# Config consistency
# ============================================================================

class TestConfigConsistency:
    """Default config must be consistent and resettable."""

    def test_default_subagent_depth_is_1(self):
        config = SubagentConfig()
        assert config.default_subagent_depth == 1

    def test_default_task_permission_deny(self):
        config = SubagentConfig()
        assert config.default_task_permission_deny is True

    def test_singleton_returns_same_instance(self):
        reset_subagent_config()
        c1 = get_subagent_config()
        c2 = get_subagent_config()
        assert c1 is c2

    def test_set_and_reset_config(self):
        reset_subagent_config()
        custom = SubagentConfig(
            default_subagent_depth=2,
            flags=SubagentFeatureFlags(subagents_enabled=True),
        )
        set_subagent_config(custom)
        assert get_subagent_config().default_subagent_depth == 2
        assert get_subagent_config().flags.subagents_enabled is True

        # Reset
        reset_subagent_config()
        assert get_subagent_config().default_subagent_depth == 1
        assert get_subagent_config().flags.subagents_enabled is False

    def test_feature_flag_off_no_extra_calls(self):
        """When all flags are off, capability reports nothing enabled."""
        config = SubagentConfig()
        cap = config.capability
        assert not any([
            cap.subagents_enabled,
            cap.task,
            cap.mention,
            cap.child_tasks,
        ])
