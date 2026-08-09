/* Auto-generated. Edit protocol/subagents_schema.json then run: bun run generate */

/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "agent_mode".
 */
export type AgentMode = "primary" | "subagent" | "all";
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "workspace_mode".
 */
export type WorkspaceMode = "read_only" | "leased_write" | "isolated_worktree";
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "trigger_kind".
 */
export type TriggerKind = "automatic" | "mention" | "command" | "team";
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "child_status".
 */
export type ChildStatus =
  "created" | "queued" | "running" | "finalizing" | "completed" | "failed" | "cancelled" | "denied" | "timed_out";
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "permission_verdict".
 */
export type PermissionVerdict = "allow" | "ask" | "deny";

/**
 * Machine-verifiable protocol schema for AgentDefinition, TaskRequest, TaskResult, and ChildSessionEvent. Mirrors protocol/subagents.py dataclasses.
 */
export interface RxyCodeSubagentProtocolV1 {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "permission_spec".
 */
export interface PermissionSpec {
  read?:
    | string
    | {
        [k: string]: unknown;
      };
  edit?:
    | string
    | {
        [k: string]: unknown;
      };
  bash?:
    | string
    | {
        [k: string]: unknown;
      };
  webfetch?:
    | string
    | {
        [k: string]: unknown;
      };
  websearch?:
    | string
    | {
        [k: string]: unknown;
      };
  task?:
    | string
    | {
        [k: string]: unknown;
      };
  external_directory?: PermissionVerdict;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "agent_definition".
 */
export interface AgentDefinition {
  id: string;
  description: string;
  mode: AgentMode;
  prompt?: string | null;
  model?: string | null;
  steps?: number | null;
  permission?: PermissionSpec;
  hidden?: boolean;
  subagent_depth?: number;
  workspace_scope?: WorkspaceMode;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "context_reference".
 */
export interface ContextReference {
  kind?: "file" | "directory" | "item" | "artifact";
  path?: string;
  item_id?: string;
  sha256?: string;
  visibility?: "full" | "summary";
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "context_envelope".
 */
export interface ContextEnvelope {
  parent_session_id: string;
  task: string;
  references?: ContextReference[];
  attachments?: string[];
  redactions?: string[];
  max_context_tokens?: number;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "task_request".
 */
export interface TaskRequest {
  request_id?: string;
  parent_session_id?: string;
  agent_id: string;
  prompt: string;
  context?: ContextEnvelope;
  trigger?: TriggerKind;
  output_schema?: string | null;
  requested_budget?: BudgetSpec;
  requested_workspace?: WorkspaceScope;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "budget_spec".
 */
export interface BudgetSpec {
  max_steps?: number;
  max_tokens?: number;
  max_wall_time_seconds?: number;
  max_concurrent_children?: number;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "workspace_scope".
 */
export interface WorkspaceScope {
  mode: WorkspaceMode;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "usage_record".
 */
export interface UsageRecord {
  steps?: number;
  input_tokens?: number;
  output_tokens?: number;
  wall_time_ms?: number;
  retry_count?: number;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "error_record".
 */
export interface ErrorRecord {
  code: string;
  message: string;
  details?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "task_result".
 */
export interface TaskResult {
  request_id: string;
  child_session_id: string;
  status: ChildStatus;
  summary?: string;
  artifacts?: ArtifactRef[];
  evidence?: EvidenceRef[];
  usage?: UsageRecord;
  error?: ErrorRecord | null;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "artifact_ref".
 */
export interface ArtifactRef {
  kind: string;
  ref: string;
  sha256?: string;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "evidence_ref".
 */
export interface EvidenceRef {
  path: string;
  line: number;
  sha256?: string;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "child_session_event".
 */
export interface ChildSessionEvent {
  event_id?: string;
  event_name: string;
  session_id: string;
  parent_session_id: string;
  request_id?: string;
  seq?: number;
  timestamp?: number;
  definition_version?: string;
  redaction_metadata?: string;
  payload?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "agent_invoke_request".
 */
export interface AgentInvokeRequest {
  agent_id: string;
  prompt: string;
  parent_session_id?: string;
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RxyCodeSubagentProtocolV1`'s JSON-Schema
 * via the `definition` "task_start_request".
 */
export interface TaskStartRequest {
  agent_id: string;
  prompt: string;
  parent_session_id?: string;
  output_schema?: string | null;
  requested_budget?: BudgetSpec;
  requested_workspace?: WorkspaceScope;
  [k: string]: unknown;
}
