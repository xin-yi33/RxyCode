import axios from "axios";
import { API_BASE, authorizationHeaders } from "../apiClient.ts";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import type { QuestionReply } from "../questionInfo.ts";
import type { StatusInfo } from "../types.ts";

export type CommandResult = {
  ok: boolean;
  action?: string;
  message?: string;
  error?: string;
  [key: string]: unknown;
};

function commandError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.code === "ECONNREFUSED" || err.code === "ENOTFOUND") {
      return "无法连接 API 服务";
    }
    const detail = err.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message) return message;
    }
    return err.message || "无法连接 API 服务";
  }
  return err instanceof Error ? err.message : "无法连接 API 服务";
}

function normalizeCommandPayload(
  data: Record<string, unknown> | null | undefined,
): CommandResult {
  if (!data) {
    return { ok: false, error: "API 返回空响应" };
  }
  const action = typeof data.action === "string" ? data.action : undefined;
  const message = typeof data.message === "string" ? data.message : undefined;
  if (action === "error") {
    return {
      ok: false,
      action,
      message,
      error: message || "命令失败",
      ...data,
    };
  }
  return { ok: true, action, message, ...data };
}

/** HTTP admin API used by both http transport and stdio hybrid mode. */
export async function httpFetchStatus(
  onStatus: (status: StatusInfo | null) => void,
): Promise<void> {
  const s = await httpFetchStatusValue();
  onStatus(s);
}

/** Fetch full /status payload; returns null when the backend is offline. */
export async function httpFetchStatusValue(signal?: AbortSignal): Promise<StatusInfo | null> {
  try {
    const resp = await axios.get(`${API_BASE}/status`, {
      timeout: 5000,
      headers: authorizationHeaders(),
      signal,
    });
    if (signal?.aborted) throw createAbortError();
    return resp.data as StatusInfo;
  } catch (error) {
    if (signal?.aborted || (error instanceof Error && error.name === "AbortError")) {
      throw createAbortError();
    }
    return null;
  }
}

function createAbortError(): Error {
  const error = new Error("Request aborted");
  error.name = "AbortError";
  return error;
}

export async function httpSendCommand(command: string): Promise<CommandResult> {
  try {
    const resp = await axios.post(
      `${API_BASE}/command`,
      { command },
      { headers: authorizationHeaders(), timeout: 15000 },
    );
    return normalizeCommandPayload(
      (resp.data ?? null) as Record<string, unknown> | null,
    );
  } catch (err: unknown) {
    return { ok: false, error: commandError(err) };
  }
}

export async function httpCancelActiveRequest(): Promise<void> {
  try {
    await axios.post(`${API_BASE}/cancel`, undefined, {
      headers: authorizationHeaders(),
      timeout: 5000,
    });
  } catch {
    // best-effort
  }
}

export async function httpRespondApproval(
  approvalId: string,
  decision: ApprovalDecision,
): Promise<boolean> {
  if (!approvalId) return false;
  try {
    await axios.post(
      `${API_BASE}/approve`,
      { approval_id: approvalId, decision },
      { headers: authorizationHeaders(), timeout: 10000 },
    );
    return true;
  } catch {
    return false;
  }
}

export async function httpRespondQuestion(
  questionId: string,
  reply: QuestionReply,
): Promise<boolean> {
  if (!questionId) return false;
  try {
    await axios.post(
      `${API_BASE}/question/respond`,
      {
        question_id: questionId,
        answer: reply.cancelled || reply.timedOut ? undefined : (reply.answer ?? ""),
        cancelled: Boolean(reply.cancelled),
      },
      { headers: authorizationHeaders(), timeout: 10000 },
    );
    return true;
  } catch {
    return false;
  }
}
