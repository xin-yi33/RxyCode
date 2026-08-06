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
]
