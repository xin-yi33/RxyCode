/* Auto-generated reference types matching protocol/subagents.py dataclasses.
   Edit protocol/subagents.py then re-sync from protocol/subagents_schema.json.
   Generate: json2ts -i ../../protocol/subagents_schema.json -o src/generated/subagent-types.ts */

export type AgentMode = "primary" | "subagent" | "all";
export type WorkspaceMode = "read_only" | "leased_write" | "isolated_worktree";
export type TriggerKind = "automatic" | "mention" | "command" | "team";
export type ChildStatus =
  | "created" | "queued" | "running" | "finalizing"
  | "completed" | "failed" | "cancelled" | "denied" | "timed_out";
export type PermissionVerdict = "allow" | "ask" | "deny";

export interface PermissionSpec {
  read?: string | Record<string, unknown>;
  edit?: string | Record<string, unknown>;
  bash?: string | Record<string, unknown>;
  webfetch?: string | Record<string, unknown>;
  websearch?: string | Record<string, unknown>;
  task?: string | Record<string, unknown>;
  external_directory?: PermissionVerdict;
}

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
}

export interface ContextReference {
  kind: "file" | "directory" | "item" | "artifact";
  path?: string;
  item_id?: string;
  sha256?: string;
  visibility?: "full" | "summary";
}

export interface ContextEnvelope {
  parent_session_id: string;
  task: string;
  references?: ContextReference[];
  attachments?: string[];
  redactions?: string[];
  max_context_tokens?: number;
}

export interface BudgetSpec {
  max_steps?: number;
  max_tokens?: number;
  max_wall_time_seconds?: number;
  max_concurrent_children?: number;
}

export interface WorkspaceScope {
  mode: WorkspaceMode;
}

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
}

export interface UsageRecord {
  steps?: number;
  input_tokens?: number;
  output_tokens?: number;
  wall_time_ms?: number;
  retry_count?: number;
}

export interface ErrorRecord {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ArtifactRef {
  kind: string;
  ref: string;
  sha256?: string;
}

export interface EvidenceRef {
  path: string;
  line: number;
  sha256?: string;
}

export interface TaskResult {
  request_id: string;
  child_session_id: string;
  status: ChildStatus;
  summary?: string;
  artifacts?: ArtifactRef[];
  evidence?: EvidenceRef[];
  usage?: UsageRecord;
  error?: ErrorRecord | null;
}

export interface ChildSessionEvent {
  event_id?: string;
  event_name: string;
  session_id: string;
  parent_session_id: string;
  request_id?: string;
  seq?: number;
  timestamp?: number;
  definition_version?: string;
  payload?: Record<string, unknown>;
}

/** RPC request types for subagent methods */
export interface AgentInvokeRequest {
  agent_id: string;
  prompt: string;
  parent_session_id?: string;
}

export interface TaskStartRequest {
  agent_id: string;
  prompt: string;
  parent_session_id?: string;
  output_schema?: string | null;
  requested_budget?: BudgetSpec;
  requested_workspace?: WorkspaceScope;
}
