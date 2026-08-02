import type { ApprovalDecision, ApprovalInfo } from "./ApprovalDialog.tsx";
import { getChatTransport } from "./transport/index.ts";
import type { ChatApiCallbacks, MessageUpdater } from "./transport/types.ts";
import type { Mode, StatusInfo } from "./types.ts";

export type { ChatApiCallbacks, MessageUpdater };

export async function fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
  return getChatTransport().fetchStatus(onStatus);
}

export async function sendCommand(command: string): Promise<Record<string, unknown> | null> {
  return getChatTransport().sendCommand(command);
}

export async function cancelActiveRequest(): Promise<void> {
  return getChatTransport().cancelActiveRequest();
}

export async function respondApproval(
  approvalId: string,
  decision: ApprovalDecision,
): Promise<boolean> {
  return getChatTransport().respondApproval(approvalId, decision);
}

export async function sendChatMessage(
  content: string,
  mode: Mode,
  callbacks: ChatApiCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return getChatTransport().sendChatMessage(content, mode, callbacks, signal);
}

export type { ApprovalInfo };
