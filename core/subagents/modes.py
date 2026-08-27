"""Session mode management, capability reporting, and feature flags.

B3 · Ties AgentDefinition modes to runtime session identity and exposes
capability discovery for CLI/Desktop/LinkAgent consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os

from protocol.subagents import AgentMode


# ---------------------------------------------------------------------------
# Feature flags — product default: isolated subagents ON
# (task + @mention). Child→child recursion stays off. Set
# RXYCODE_SUBAGENTS=0 to restore the single-agent-only baseline.
# ---------------------------------------------------------------------------

@dataclass
class SubagentFeatureFlags:
    """Runtime feature flags controlling subagent availability.

    Blank ``SubagentFeatureFlags()`` stays all-off for explicit test setups.
    The product default is ``subagent_config_from_env()`` (master/task/mention on).
    """

    # Master kill-switch: when False, no subagent paths are available
    subagents_enabled: bool = False

    # Allow model to dispatch via Task Tool (automatic trigger)
    subagents_task: bool = False

    # Allow user @agent mention
    subagents_mention: bool = False

    # Allow child agents to spawn further children
    subagents_child_tasks: bool = False


# ---------------------------------------------------------------------------
# Capability report
# ---------------------------------------------------------------------------

@dataclass
class SubagentCapability:
    """Capability report exposed to clients via appserver.

    Clients MUST check capabilities before offering subagent UI elements.
    They MUST NOT hard-code assumptions about availability.
    """

    # Server-wide
    protocol_version: int = 1
    subagents_enabled: bool = False

    # Per-feature
    task: bool = False         # Task Tool automatic dispatch
    mention: bool = False      # User @agent invocation
    child_tasks: bool = False  # Child→child recursion


def build_capability(flags: SubagentFeatureFlags) -> SubagentCapability:
    """Build a capability report from current feature flags."""
    return SubagentCapability(
        protocol_version=1,
        subagents_enabled=flags.subagents_enabled,
        task=flags.subagents_task,
        mention=flags.subagents_mention,
        child_tasks=flags.subagents_child_tasks,
    )


# ---------------------------------------------------------------------------
# Session mode
# ---------------------------------------------------------------------------

class SessionMode(str, Enum):
    """The agent mode a running session is operating under."""
    PRIMARY = "primary"
    CHILD = "child"


@dataclass
class SessionIdentity:
    """Identity metadata attached to a running session."""

    session_mode: SessionMode = SessionMode.PRIMARY
    agent_id: str = "primary"          # Which AgentDefinition this session runs as
    parent_session_id: str = ""        # Empty for Primary sessions
    root_session_id: str = ""          # Topmost Primary session id


# ---------------------------------------------------------------------------
# Entry validation
# ---------------------------------------------------------------------------

def validate_primary_entry(agent_mode: AgentMode) -> None:
    """Validate that an agent mode is allowed for user-facing primary entry.

    Raises ValueError if the mode cannot serve as a user-facing primary.
    """
    if agent_mode not in (AgentMode.PRIMARY, AgentMode.ALL):
        raise ValueError(
            f"Agent mode '{agent_mode.value}' cannot serve as a user-facing primary. "
            f"Only 'primary' and 'all' modes are allowed."
        )


def validate_subagent_entry(agent_mode: AgentMode, *, is_subtask_command: bool = False) -> None:
    """Validate that an agent mode can be dispatched as a child/subagent.

    Args:
        agent_mode: The mode to validate.
        is_subtask_command: If True, primary/all agents can be forced into child mode
                           (this is the ``subtask=true`` exception).

    Raises ValueError if the mode cannot be dispatched as a child.
    """
    if is_subtask_command:
        # subtask=true forces any primary/all/subagent agent into a child session
        if agent_mode not in (AgentMode.PRIMARY, AgentMode.SUBAGENT, AgentMode.ALL):
            raise ValueError(f"Invalid agent mode '{agent_mode.value}' for subtask.")
        return

    if agent_mode not in (AgentMode.SUBAGENT, AgentMode.ALL):
        raise ValueError(
            f"Agent mode '{agent_mode.value}' cannot be dispatched as a child. "
            f"Only 'subagent' and 'all' modes are allowed for Task/@ dispatch."
        )


# ---------------------------------------------------------------------------
# Default configuration provider
# ---------------------------------------------------------------------------

@dataclass
class SubagentConfig:
    """Default subagent configuration.

    These are the hard-coded server defaults. They can be overridden by
    per-agent definitions and EffectiveTaskPolicy, but never made more
    permissive than the system hard-reject rules.
    """

    # Global depth limit (server-wide)
    default_subagent_depth: int = 1

    # Default task permission — deny all unless explicitly allowed
    default_task_permission_deny: bool = True

    # Aggregate token budget for one child task. Worker bootstrap resolves
    # this from active-model metadata; this is the unknown-model fallback.
    default_max_tokens: int = 131072

    # Feature flags
    flags: SubagentFeatureFlags = field(default_factory=SubagentFeatureFlags)

    @property
    def capability(self) -> SubagentCapability:
        return build_capability(self.flags)


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if not value:
        return default
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def subagent_config_from_env(*, default_max_tokens: int | None = None) -> SubagentConfig:
    """Build worker-local feature flags from environment switches.

    Defaults (unset env): enabled + task + mention ON; child_tasks OFF.
    ``RXYCODE_SUBAGENTS=0`` is the master kill-switch.
    """
    enabled = _env_flag("RXYCODE_SUBAGENTS", True)
    flags = SubagentFeatureFlags(
        subagents_enabled=enabled,
        subagents_task=enabled and _env_flag("RXYCODE_SUBAGENTS_TASK", True),
        subagents_mention=enabled and _env_flag("RXYCODE_SUBAGENTS_MENTION", True),
        subagents_child_tasks=(
            enabled and _env_flag("RXYCODE_SUBAGENTS_CHILD_TASKS", False)
        ),
    )
    return SubagentConfig(
        flags=flags,
        default_max_tokens=(
            default_max_tokens
            if isinstance(default_max_tokens, int) and default_max_tokens > 0
            else 131072
        ),
    )


# ---------------------------------------------------------------------------
# Singleton config (per-process)
# ---------------------------------------------------------------------------

_config: SubagentConfig | None = None


def get_subagent_config() -> SubagentConfig:
    """Return the process-wide subagent configuration singleton."""
    global _config
    if _config is None:
        _config = subagent_config_from_env()
    return _config


def set_subagent_config(config: SubagentConfig) -> None:
    """Replace the process-wide subagent configuration.

    Must be called before any child sessions are created.
    """
    global _config
    _config = config


def reset_subagent_config() -> SubagentConfig:
    """Reset to product defaults from the environment (used in tests)."""
    global _config
    _config = subagent_config_from_env()
    return _config
