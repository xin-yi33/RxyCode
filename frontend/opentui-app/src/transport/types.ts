import type { ApprovalDecision, ApprovalInfo } from "../ApprovalDialog.tsx";
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
}

export type TransportKind = "http" | "stdio";

export interface ChatTransport {
  readonly kind: TransportKind;
  fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void>;
  sendCommand(command: string): Promise<CommandResult>;
  cancelActiveRequest(): Promise<void>;
  respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean>;
  sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
  ): Promise<void>;
  invokeSubagent(agentId: string, prompt: string): Promise<SubagentResult>;
  shutdown?(): Promise<void>;
}

/** Phase B result of `agent/invoke` (mirrors appserver/subagent_routes._result_to_dict). */
export interface SubagentResult {
  request_id: string;
  child_session_id: string;
  status: string;
  summary: string;
  artifacts: Array<{ kind: string; ref: string; sha256: string | null }>;
  evidence: Array<{ path: string; line: number | null; sha256: string | null }>;
  usage: { steps: number; input_tokens: number; output_tokens: number };
  error: { code: string; message: string } | null;
}
