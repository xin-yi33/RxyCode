/**
 * Pure SSE chat state reducer — OpenTUI only (mirrors Ink settle / thinking timing).
 * Thinking stays done=false until final/settle; tokens must NOT checkmark Thought early.
 */

import type { ChatMessage, ToolStatus } from "./types.ts";

export interface StreamEvent {
  type: string;
  text?: string;
  thinking?: string;
  message?: string;
  name?: string;
  args?: string | Record<string, unknown>;
  result?: string;
  status?: string;
  exitCode?: number;
  duration?: number;
  error?: string;
  snapshot?: boolean;
  approval_id?: string;
  tool?: string;
  risk?: string;
}

export interface StreamReduceState {
  messages: ChatMessage[];
  thinkingId: string;
  assistantId: string;
  acc: string;
  assistantCreated: boolean;
  reasoningAcc: string;
  hasReasoning: boolean;
  finalText?: string;
}

export function settleActiveMessages(
  messages: ChatMessage[],
  toolStatus: Extract<ToolStatus, "error" | "timeout" | "cancelled"> = "cancelled",
): ChatMessage[] {
  return messages.map((message) => {
    if (message.role === "assistant" && message.done !== true) {
      return { ...message, done: true };
    }
    if (message.role === "thinking" && (message.done !== true || message.live !== false)) {
      return { ...message, done: true, live: false };
    }
    if (message.role === "tool" && message.toolStatus === "running") {
      return { ...message, toolStatus };
    }
    return message;
  });
}

export function applyStreamEvent(
  state: StreamReduceState,
  event: StreamEvent,
  newId: (suffix: string) => string,
): StreamReduceState {
  const next: StreamReduceState = { ...state, messages: state.messages };

  switch (event.type) {
    case "reasoning":
    case "thinking": {
      const thought = event.thinking || event.text || "";
      if (!thought) return next;
      let reasoningAcc = next.reasoningAcc;
      if (event.snapshot || !next.hasReasoning) {
        reasoningAcc = thought;
      } else {
        // Multi-round: keep accumulating after tools (OpenCode-style).
        const sep = reasoningAcc && !reasoningAcc.endsWith("\n") ? "\n" : "";
        reasoningAcc = reasoningAcc + sep + thought;
      }
      return {
        ...next,
        reasoningAcc,
        hasReasoning: true,
        messages: next.messages.map((m) =>
          m.id === next.thinkingId
            ? { ...m, content: reasoningAcc, live: true, done: false }
            : m,
        ),
      };
    }
    case "token": {
      if (!event.text) return next;
      const acc = next.acc + event.text;
      if (!next.assistantCreated) {
        return {
          ...next,
          acc,
          assistantCreated: true,
          // CRITICAL: do NOT mark thinking done on first token
          messages: [
            ...next.messages,
            {
              id: next.assistantId,
              role: "assistant",
              content: acc,
              timestamp: Date.now(),
              done: false,
            },
          ],
        };
      }
      return {
        ...next,
        acc,
        messages: next.messages.map((m) =>
          m.id === next.assistantId ? { ...m, content: acc } : m,
        ),
      };
    }
    case "tool_call":
      return {
        ...next,
        messages: [
          ...next.messages,
          {
            id: newId("tool"),
            role: "tool",
            content:
              typeof event.args === "string"
                ? event.args
                : event.args
                  ? JSON.stringify(event.args)
                  : "",
            timestamp: Date.now(),
            toolName: event.name || "tool",
            toolStatus: "running",
          },
        ],
      };
    case "tool_result": {
      const status: ToolStatus =
        event.status === "error" || event.status === "timeout" || event.status === "cancelled"
          ? (event.status as ToolStatus)
          : "success";
      const idx = [...next.messages]
        .reverse()
        .findIndex(
          (m) =>
            m.role === "tool" &&
            m.toolName === (event.name || m.toolName) &&
            m.toolStatus === "running",
        );
      if (idx < 0) return next;
      const realIdx = next.messages.length - 1 - idx;
      const messages = [...next.messages];
      messages[realIdx] = {
        ...messages[realIdx],
        toolStatus: status,
        content: event.result || event.error || messages[realIdx].content,
      };
      return { ...next, messages };
    }
    case "final": {
      const finalText = event.text ?? event.message ?? next.acc;
      // Mark thinking done on final (Ink parity); assistant may still settle later.
      let messages = next.messages.map((m) =>
        m.id === next.thinkingId
          ? {
              ...m,
              done: true,
              live: false,
              content: next.hasReasoning ? next.reasoningAcc : m.content === "…" ? "Done" : m.content,
            }
          : m,
      );
      const hasAssistant = messages.some((m) => m.id === next.assistantId);
      if (hasAssistant) {
        messages = messages.map((m) =>
          m.id === next.assistantId ? { ...m, content: finalText, done: false } : m,
        );
      } else if (finalText) {
        messages = [
          ...messages,
          {
            id: next.assistantId,
            role: "assistant",
            content: finalText,
            timestamp: Date.now(),
            done: false,
          },
        ];
      }
      return {
        ...next,
        finalText,
        assistantCreated: true,
        acc: finalText || next.acc,
        messages,
      };
    }
    case "error":
      return {
        ...next,
        messages: [
          ...next.messages,
          {
            id: newId("system"),
            role: "system",
            content: event.error || event.message || "Request failed",
            timestamp: Date.now(),
          },
        ],
      };
    default:
      return next;
  }
}
