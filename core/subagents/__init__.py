"""Phase B · Isolated Subagent Runtime.

Public facade exports:
  - AgentDefinition, TaskRequest, TaskResult (from protocol)
  - AgentDefinitionRegistry, load_agent_definitions (from definitions)
  - ChildRuntime (from runtime, when B5 is implemented)
"""

from protocol.subagents import (
    AgentDefinition,
    AgentMode,
    BudgetSpec,
    ChildStatus,
    ContextEnvelope,
    ContextReference,
    EffectiveTaskPolicy,
    ErrorRecord,
    EvidenceRef,
    PermissionRule,
    PermissionSpec,
    PermissionVerdict,
    TaskPermissionSpec,
    TaskRequest,
    TaskResult,
    ToolPermission,
    TriggerKind,
    UsageRecord,
    WorkspaceMode,
    WorkspaceScope,
)

from .definitions import (
    AgentDefinitionRegistry,
    DefinitionError,
    load_agent_definitions,
    validate_agent_definition,
)
from .modes import (
    SessionIdentity,
    SessionMode,
    SubagentCapability,
    SubagentConfig,
    SubagentFeatureFlags,
    build_capability,
    get_subagent_config,
    reset_subagent_config,
    set_subagent_config,
    validate_primary_entry,
    validate_subagent_entry,
)
from .sessions import (
    ChildSession,
    InvalidStateTransition,
    SessionNotFound,
    SessionTree,
    create_child_session,
    transition,
)

__all__ = [
    # Protocol types
    "AgentDefinition",
    "AgentMode",
    "BudgetSpec",
    "ChildStatus",
    "ContextEnvelope",
    "ContextReference",
    "EffectiveTaskPolicy",
    "ErrorRecord",
    "EvidenceRef",
    "PermissionRule",
    "PermissionSpec",
    "PermissionVerdict",
    "TaskPermissionSpec",
    "TaskRequest",
    "TaskResult",
    "ToolPermission",
    "TriggerKind",
    "UsageRecord",
    "WorkspaceMode",
    "WorkspaceScope",
    # Registry
    "AgentDefinitionRegistry",
    "DefinitionError",
    "load_agent_definitions",
    "validate_agent_definition",
    # Modes & config
    "SessionIdentity",
    "SessionMode",
    "SubagentCapability",
    "SubagentConfig",
    "SubagentFeatureFlags",
    "build_capability",
    "get_subagent_config",
    "reset_subagent_config",
    "set_subagent_config",
    "validate_primary_entry",
    "validate_subagent_entry",
    # Sessions
    "ChildSession",
    "InvalidStateTransition",
    "SessionNotFound",
    "SessionTree",
    "create_child_session",
    "transition",
]
