export {
  ProtocolClient,
  ProtocolRpcError,
  type JsonRpcErrorObject,
  type JsonRpcId,
  type NotificationHandler,
  type ServerRequestHandler,
} from "./client.ts";

export type {
  ApprovalRequest,
  ClientRequest,
  FinalAnswer,
  InitializeRequest,
  MessageDelta,
  PromptRequest,
  ProtocolNotification,
} from "./generated/types.ts";

/* Phase B: subagent protocol types */
export type {
  AgentMode,
  WorkspaceMode,
  TriggerKind,
  ChildStatus,
  PermissionVerdict,
  PermissionSpec,
  AgentDefinition,
  ContextReference,
  ContextEnvelope,
  BudgetSpec,
  WorkspaceScope,
  TaskRequest,
  UsageRecord,
  ErrorRecord,
  ArtifactRef,
  EvidenceRef,
  TaskResult,
  ChildSessionEvent,
  AgentInvokeRequest,
  TaskStartRequest,
} from "./generated/subagent-types.ts";