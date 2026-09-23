import type { ApprovalDecision, ApprovalInfo } from "../ApprovalDialog.tsx";
import type { QuestionInfo, QuestionReply } from "../questionInfo.ts";
import type { Mode, StatusInfo } from "../types.ts";
import type { CommandResult } from "./httpAdmin.ts";

export type MessageUpdater = (
  prev: import("../types.ts").ChatMessage[],
) => import("../types.ts").ChatMessage[];

export interface ChatApiCallbacks {
  onMessages: (updater: MessageUpdater) => void;
  onStreaming: (streaming: boolean) => void;
  onStatus: (status: StatusInfo | null) => void;
  onProgress?: (text: string) => void;
  onApprovalRequest?: (info: ApprovalInfo | null) => void;
  onQuestionRequest?: (info: QuestionInfo | null) => void;
  onPlan?: (doc: { title: string; body: string }) => void;
}

export type TransportKind = "http" | "stdio";

export type SteerTurnResult =
  | { ok: true; injected?: boolean }
  | { ok: false; message: string };

export interface ChatTransport {
  readonly kind: TransportKind;
  fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void>;
  sendCommand(command: string): Promise<CommandResult>;
  cancelActiveRequest(): Promise<void>;
  /** Inject text into the in-flight turn without interrupting it (`turn/steer`). */
  steerTurn(text: string, mode?: Mode): Promise<SteerTurnResult>;
  respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean>;
  respondQuestion(questionId: string, reply: QuestionReply): Promise<boolean>;
  sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
    displayContent?: string,
  ): Promise<void>;
  invokeSubagent(agentId: string, prompt: string): Promise<SubagentResult>;
  listChildSessions(): Promise<ChildNavigationEntry[]>;
  openChildSession(target: string): Promise<ChildNavigationResult>;
  openParentSession(): Promise<ChildNavigationResult>;
  shutdown?(): Promise<void>;
  listSessions(): Promise<SessionListRow[]>;
  attachSession(sessionId: string): Promise<AttachSessionResult>;
  renameSession(sessionId: string, title: string): Promise<SessionListRow>;
  trashSession(sessionId: string): Promise<void>;
  pinSession(sessionId: string, pinned: boolean): Promise<void>;
  forkSession(sessionId: string): Promise<SessionListRow>;
}

export interface SessionListRow {
  session_id: string;
  title?: string;
  display_title?: string;
  generated_title?: string | null;
  title_is_manual?: boolean;
  title_source?: string;
  age_label?: string;
  date_group?: string;
  pinned?: boolean;
  trashed_at?: string | null;
  parent_session_id?: string | null;
  forked_from?: string | null;
  updated_at?: string;
  created_at?: string;
  workspace_root?: string;
  status?: string;
}

export interface AttachSessionResult {
  session_id: string;
  messages: import("../types.ts").ChatMessage[];
}

export interface ChildNavigationEntry {
  session_id: string;
  parent_session_id?: string | null;
  agent_id?: string;
  status?: string;
}

export interface ChildNavigationResult {
  ok: boolean;
  entry?: ChildNavigationEntry;
  events?: Array<Record<string, unknown>>;
  message: string;
}

/** Phase B result of `agent/invoke` (mirrors appserver/subagent_routes._result_to_dict). */
export interface SubagentResult {
  request_id: string;
  child_session_id: string;
  status: string;
  summary: string;
  artifacts: Array<{ kind: string; ref: string; sha256: string | null }>;
  evidence: Array<{ path: string; line: number | null; sha256: string | null }>;
  usage: {
    steps: number;
    input_tokens: number | null;
    output_tokens: number | null;
    cache_hit_tokens?: number | null;
    cache_write_tokens?: number | null;
    cache_hit_rate?: number | null;
    reporting_status?: "reported" | "partial" | "not_reported";
  };
  error: { code: string; message: string } | null;
}
