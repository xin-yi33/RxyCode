import axios from "axios";
import { API_BASE, authorizationHeaders } from "./apiClient.ts";
import type { ApprovalDecision, ApprovalInfo } from "./ApprovalDialog.tsx";
import { consumeJsonSseStream } from "./sseParser.ts";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamEvent,
  type StreamReduceState,
} from "./streamReducer.ts";
import type { Mode, StatusInfo } from "./types.ts";

export type MessageUpdater = (prev: import("./types.ts").ChatMessage[]) => import("./types.ts").ChatMessage[];

export interface ChatApiCallbacks {
  onMessages: (updater: MessageUpdater) => void;
  onStreaming: (streaming: boolean) => void;
  onStatus: (status: StatusInfo | null) => void;
  onProgress?: (text: string) => void;
  onApprovalRequest?: (info: ApprovalInfo | null) => void;
}

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 7)}`;
}

export async function fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
  try {
    const resp = await axios.get(`${API_BASE}/status`, {
      timeout: 5000,
      headers: authorizationHeaders(),
    });
    onStatus(resp.data as StatusInfo);
  } catch {
    onStatus(null);
  }
}

/** POST /command — same contract as Ink useApi.sendCommand (U3 /thinking gate sync). */
export async function sendCommand(command: string): Promise<Record<string, unknown> | null> {
  try {
    const resp = await axios.post(
      `${API_BASE}/command`,
      { command },
      { headers: authorizationHeaders(), timeout: 15000 },
    );
    return (resp.data ?? null) as Record<string, unknown> | null;
  } catch {
    return null;
  }
}

/** POST /cancel — parity with Ink useApi.cancelRequest (Esc under PTY). */
export async function cancelActiveRequest(): Promise<void> {
  try {
    await axios.post(`${API_BASE}/cancel`, undefined, {
      headers: authorizationHeaders(),
      timeout: 5000,
    });
  } catch {
    // best-effort; local AbortSignal still stops the client
  }
}

/** POST /approve — safety gate decision (parity with Ink useApi.respondApproval). */
export async function respondApproval(
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

export async function sendChatMessage(
  content: string,
  mode: Mode,
  callbacks: ChatApiCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const userMsg = {
    id: newId("user"),
    role: "user" as const,
    content,
    timestamp: Date.now(),
    mode,
  };
  callbacks.onMessages((prev) => [...prev, userMsg]);
  callbacks.onStreaming(true);
  callbacks.onProgress?.("Connecting...");

  const thinkingId = newId("thinking");
  const assistantId = newId("assistant");

  let state: StreamReduceState = {
    messages: [
      {
        id: thinkingId,
        role: "thinking",
        content: "…",
        timestamp: Date.now(),
        live: true,
        done: false,
      },
    ],
    thinkingId,
    assistantId,
    acc: "",
    assistantCreated: false,
    reasoningAcc: "",
    hasReasoning: false,
  };

  callbacks.onMessages((prev) => [...prev, ...state.messages]);

  const publish = (next: StreamReduceState) => {
    state = next;
    callbacks.onMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === userMsg.id);
      if (idx < 0) return [...prev, ...next.messages];
      return [...prev.slice(0, idx + 1), ...next.messages];
    });
  };

  try {
    let resp: Response | null = null;
    let lastErr: unknown = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        resp = await fetch(`${API_BASE}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authorizationHeaders() },
          body: JSON.stringify({ message: content, mode }),
          signal,
        });
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e;
        if (attempt === 0) await new Promise((r) => setTimeout(r, 1500));
      }
    }

    if (!resp) {
      throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
    }
    if (!resp.ok || !resp.body) {
      throw new Error(`Chat stream failed: HTTP ${resp.status}`);
    }

    const reader = resp.body.getReader();

    await consumeJsonSseStream<StreamEvent>(
      reader,
      (event) => {
        if (event.type === "progress" && !state.hasReasoning) {
          callbacks.onProgress?.(event.message || event.text || "Working...");
        }
        if (event.type === "tool_call") {
          callbacks.onProgress?.(event.name ? `Tool: ${event.name}` : "Running tool...");
        }
        if (event.type === "approval_request") {
          const args = event.args;
          callbacks.onApprovalRequest?.({
            approvalId: String(event.approval_id || ""),
            tool: String(event.tool || event.name || "unknown"),
            risk: String(event.risk || "WRITE"),
            args: typeof args === "string" ? args : JSON.stringify(args ?? {}),
          });
        }
        if (event.type === "tool_result") {
          callbacks.onApprovalRequest?.(null);
        }
        const next = applyStreamEvent(state, event, newId);
        if (next !== state) publish(next);
      },
      (event) => event.type === "final" || event.type === "done",
    );

    publish({
      ...state,
      messages: settleActiveMessages(state.messages),
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") {
      publish({
        ...state,
        messages: [
          ...settleActiveMessages(state.messages, "cancelled"),
          {
            id: newId("system"),
            role: "system",
            content: "Cancelled.",
            timestamp: Date.now(),
          },
        ],
      });
    } else {
      callbacks.onMessages((prev) => [
        ...settleActiveMessages(prev),
        {
          id: newId("system"),
          role: "system",
          content: e instanceof Error ? e.message : String(e),
          timestamp: Date.now(),
        },
      ]);
    }
  } finally {
    callbacks.onStreaming(false);
    callbacks.onProgress?.("");
    void fetchStatus(callbacks.onStatus);
  }
}
