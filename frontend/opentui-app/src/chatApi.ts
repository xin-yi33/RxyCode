import type { ApprovalDecision, ApprovalInfo } from "./ApprovalDialog.tsx";
import type { QuestionReply } from "./questionInfo.ts";
import { getChatTransport } from "./transport/index.ts";
import type { CommandResult } from "./transport/httpAdmin.ts";
import type { ChatApiCallbacks, MessageUpdater } from "./transport/types.ts";
import type { Mode, StatusInfo } from "./types.ts";

export { getChatTransport };
export type { ChatApiCallbacks, MessageUpdater };

export async function fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
  return getChatTransport().fetchStatus(onStatus);
}

export async function sendCommand(command: string): Promise<CommandResult> {
  return getChatTransport().sendCommand(command);
}

export async function cancelActiveRequest(): Promise<void> {
  return getChatTransport().cancelActiveRequest();
}

export async function steerTurn(text: string, mode?: Mode) {
  return getChatTransport().steerTurn(text, mode);
}

export async function respondApproval(
  approvalId: string,
  decision: ApprovalDecision,
): Promise<boolean> {
  return getChatTransport().respondApproval(approvalId, decision);
}

export async function respondQuestion(
  questionId: string,
  reply: QuestionReply,
): Promise<boolean> {
  return getChatTransport().respondQuestion(questionId, reply);
}

export async function sendChatMessage(
  content: string,
  mode: Mode,
  callbacks: ChatApiCallbacks,
  signal?: AbortSignal,
  displayContent?: string,
): Promise<void> {
  return getChatTransport().sendChatMessage(content, mode, callbacks, signal, displayContent);
}

export async function invokeSubagent(agentId: string, prompt: string) {
  return getChatTransport().invokeSubagent(agentId, prompt);
}

export async function listChildSessions() {
  return getChatTransport().listChildSessions();
}

export async function openChildSession(target: string) {
  return getChatTransport().openChildSession(target);
}

export async function openParentSession() {
  return getChatTransport().openParentSession();
}

export type { ApprovalInfo };
export type { QuestionInfo, QuestionReply } from "./questionInfo.ts";
