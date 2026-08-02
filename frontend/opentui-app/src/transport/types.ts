import type { ApprovalDecision, ApprovalInfo } from "../ApprovalDialog.tsx";
import type { Mode, StatusInfo } from "../types.ts";

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
  sendCommand(command: string): Promise<Record<string, unknown> | null>;
  cancelActiveRequest(): Promise<void>;
  respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean>;
  sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
  ): Promise<void>;
  shutdown?(): Promise<void>;
}
