import axios from "axios";
import { API_BASE, authorizationHeaders } from "../apiClient.ts";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import { consumeJsonSseStream } from "../sseParser.ts";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamEvent,
  type StreamReduceState,
} from "../streamReducer.ts";
import type { Mode, StatusInfo } from "../types.ts";
import {
  httpCancelActiveRequest,
  httpFetchStatus,
  httpRespondApproval,
  httpSendCommand,
  type CommandResult,
} from "./httpAdmin.ts";
import type { ChatApiCallbacks, ChatTransport } from "./types.ts";

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 7)}`;
}

export const httpTransport: ChatTransport = {
  kind: "http",

  async fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
    return httpFetchStatus(onStatus);
  },

  async sendCommand(command: string): Promise<CommandResult> {
    return httpSendCommand(command);
  },

  async cancelActiveRequest(): Promise<void> {
    return httpCancelActiveRequest();
  },

  async respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean> {
    return httpRespondApproval(approvalId, decision);
  },

  async sendChatMessage(
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

    const handleEvent = (event: StreamEvent) => {
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
        handleEvent,
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
      void httpTransport.fetchStatus(callbacks.onStatus);
    }
  },
};
