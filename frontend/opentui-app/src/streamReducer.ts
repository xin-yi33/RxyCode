/**
 * Pure SSE chat state reducer — OpenTUI only.
 * Thought slices close on tool_call / token so they interleave with tools and body
 * (OpenCode: think → tool → think), instead of one Thought accumulating at the top.
 */

import type { ChatMessage, ToolStatus } from "./types.ts";
import { summarizeQuestionToolArgs } from "./questionInfo.ts";
import { nextThoughtExpanded } from "./lib/thinkingDisplay.ts";
import { serializeToolArgs } from "./lib/toolDisplay.ts";

const THOUGHT_PLACEHOLDERS = new Set([
  "",
  "…",
  "...",
  "思考中...",
  "思考中…",
  "Done",
  "正在思考中...",
  "已思考完毕",
]);

function isPlaceholderThought(text: string): boolean {
  return THOUGHT_PLACEHOLDERS.has((text || "").trim());
}

function closeOpenThoughts(messages: ChatMessage[], now = Date.now()): ChatMessage[] {
  return messages.map((m) =>
    m.role === "thinking" && m.done !== true
      ? { ...m, done: true, live: false, endedAt: m.endedAt ?? now }
      : m,
  );
}

function thoughtNeedsNewSlice(state: StreamReduceState): boolean {
  const idx = state.messages.findIndex((m) => m.id === state.thinkingId);
  const current = idx >= 0 ? state.messages[idx] : undefined;
  if (!current || current.done === true) return true;
  return state.messages.slice(idx + 1).some((m) => m.role === "tool" || m.role === "assistant");
}

export interface StreamEvent {
  type: string;
  text?: string;
  thinking?: string;
  message?: string;
  call_id?: string;
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
  question_id?: string;
  question?: string;
  header?: string;
  options?: Array<{ label: string; value: string }>;
  input_type?: string;
  /* Phase B: child session fields */
  childSessionId?: string;
  childStatus?: string;
  parentSessionId?: string;
  agentId?: string;
  usage?: Record<string, unknown>;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_hit_tokens?: number | null;
  cache_hit_rate?: number | null;
  reporting_status?: string;
  context_used?: number | null;
  steps?: string[];
  /** 2026-09-23（P0 answer-last）：子代理中间输出。token/reasoning/progress
   *  带此标记时不进主聊流（不进 messages），避免「中间阶段文本」被渲染成
   *  最终答复的样子。 */
  intermediate?: boolean;
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
      return {
        ...message,
        done: true,
        live: false,
        endedAt: message.endedAt ?? Date.now(),
      };
    }
    if (message.role === "tool" && message.toolStatus === "running") {
      return { ...message, toolStatus, endedAt: message.endedAt ?? Date.now() };
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
      // 2026-09-23（P0 answer-last）：子代理的思维链不进主聊流。
      if (event.intermediate) return next;
      const thought = event.thinking || event.text || "";
      if (!thought || isPlaceholderThought(thought)) return next;
      if (thoughtNeedsNewSlice(next)) {
        const id = newId("thinking");
        return {
          ...next,
          thinkingId: id,
          reasoningAcc: thought,
          hasReasoning: true,
          messages: [
            ...closeOpenThoughts(next.messages),
            {
              id,
              role: "thinking" as const,
              content: thought,
              timestamp: Date.now(),
              live: true,
              done: false,
              hasReasoning: true,
              expanded: nextThoughtExpanded(),
            },
          ],
        };
      }
      let reasoningAcc = next.reasoningAcc;
      if (event.snapshot || !next.hasReasoning) {
        if (
          next.reasoningAcc &&
          !isPlaceholderThought(next.reasoningAcc) &&
          isPlaceholderThought(thought)
        ) {
          reasoningAcc = next.reasoningAcc;
        } else {
          reasoningAcc = thought;
        }
      } else {
        // Provider chunks are word/token pieces. Do not insert newlines or
        // expand-Thought renders one fragment per line.
        reasoningAcc = reasoningAcc + thought;
      }
      return {
        ...next,
        reasoningAcc,
        hasReasoning: true,
        messages: next.messages.map((m) =>
          m.id === next.thinkingId
            ? {
                ...m,
                content: reasoningAcc,
                live: true,
                done: false,
                hasReasoning: true,
              }
            : m,
        ),
      };
    }
    case "token": {
      if (!event.text) return next;
      // 2026-09-23（P0 answer-last）：子代理（专家团各阶段）的流式文本
      // 不进主聊流——它是中间过程，不是给用户的答复。主代理文本不受影响。
      if (event.intermediate) return next;
      const last = next.messages.at(-1);
      const attachToTail = last?.role === "assistant" && last.id === next.assistantId;
      if (attachToTail) {
        const acc = next.acc + event.text;
        return {
          ...next,
          acc,
          messages: next.messages.map((m) =>
            m.id === next.assistantId ? { ...m, content: acc } : m,
          ),
        };
      }
      const id = next.assistantCreated ? newId("assistant") : next.assistantId;
      return {
        ...next,
        acc: event.text,
        assistantCreated: true,
        assistantId: id,
        messages: [
          ...closeOpenThoughts(next.messages),
          {
            id,
            role: "assistant" as const,
            content: event.text,
            timestamp: Date.now(),
            done: false,
          },
        ],
      };
    }
    case "tool_call": {
      const last = next.messages.at(-1);
      const toolName = event.name || "tool";
      const toolArgs = serializeToolArgs(event.args);
      const content =
        toolName === "question" ? summarizeQuestionToolArgs(event.args) : "";
      return {
        ...next,
        messages: [
          ...closeOpenThoughts(next.messages),
          {
            id: newId("tool"),
            role: "tool",
            content,
            timestamp: Date.now(),
            toolName,
            toolCallId: event.call_id || undefined,
            toolStatus: "running",
            toolArgs,
            toolExpanded: true,
          },
        ],
      };
    }
    case "tool_result": {
      const status: ToolStatus =
        event.status === "error" || event.status === "timeout" || event.status === "cancelled"
          ? (event.status as ToolStatus)
          : "success";
      const wantedId = String(event.call_id || "");
      const idx = [...next.messages]
        .reverse()
        .findIndex((m) => {
          if (m.role !== "tool" || m.toolStatus !== "running") return false;
          if (wantedId && m.toolCallId) return m.toolCallId === wantedId;
          return m.toolName === (event.name || m.toolName);
        });
      if (idx < 0) return next;
      const realIdx = next.messages.length - 1 - idx;
      const messages = [...next.messages];
      messages[realIdx] = {
        ...messages[realIdx],
        toolStatus: status,
        content: event.result || event.error || messages[realIdx].content,
        endedAt: Date.now(),
        toolExpanded: true,
      };
      return { ...next, messages };
    }
    case "final": {
      const finalText = event.text ?? event.message ?? next.acc;
      const finalThought = String(event.thinking || "").trim();
      let seeded = next;
      if (finalThought && !isPlaceholderThought(finalThought) && !next.hasReasoning) {
        seeded = applyStreamEvent(next, { type: "reasoning", thinking: finalThought }, newId);
      }
      let messages = closeOpenThoughts(seeded.messages).map((m) =>
        m.id === seeded.thinkingId
          ? {
              ...m,
              hasReasoning: seeded.hasReasoning || m.hasReasoning,
              content: seeded.hasReasoning && seeded.reasoningAcc ? seeded.reasoningAcc : m.content,
            }
          : m,
      );
      const hasAssistant = messages.some((m) => m.role === "assistant");
      // Keep streamed segments. Do not dump the full final essay into the first bubble.
      if (!hasAssistant && finalText) {
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
        ...seeded,
        finalText,
        assistantCreated: true,
        acc: finalText || seeded.acc,
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
    /* ── Phase B: child session events ─────────────────── */
    case "child_created": {
      const childMsg = {
        id: newId("child"),
        role: "child_session" as const,
        content: event.text || `子代理 ${event.agentId ?? ""} 已创建`,
        timestamp: Date.now(),
        childSessionId: event.childSessionId,
        childStatus: "created",
        parentSessionId: event.parentSessionId,
        agentId: event.agentId,
        depth: 0,
      };
      return { ...next, messages: [...next.messages, childMsg] };
    }
    case "child_status": {
      const status = event.childStatus || "unknown";
      return {
        ...next,
        messages: next.messages.map((m) =>
          m.childSessionId && m.childSessionId === event.childSessionId
            ? { ...m, childStatus: status, content: event.text || m.content }
            : m,
        ),
      };
    }
    case "child_completed": {
      return {
        ...next,
        messages: next.messages.map((m) =>
          m.childSessionId && m.childSessionId === event.childSessionId
            ? { ...m, childStatus: "completed", content: event.text || m.content, done: true }
            : m,
        ),
      };
    }
    case "child_error": {
      return {
        ...next,
        messages: next.messages.map((m) =>
          m.childSessionId && m.childSessionId === event.childSessionId
            ? { ...m, childStatus: "failed", content: event.error || event.text || m.content, done: true }
            : m,
        ),
      };
    }
    case "progress": {
      const text = event.message || event.text || "";
      if (!text.includes("──")) return next;
      // 2026-09-23（P1b 验证内联）：专家团阶段分隔线不再进主聊流。
      // 阶段信息只走状态行（liveProgressText 的 [role] stage 分支），
      // 主聊流不再出现「──────── test · tester ────────」仪式条。
      // 废弃渲染（2026-09-23）：原先在这里 append 一条 role=system 的分隔线消息。
      return next;
    }
    default:
      return next;
  }
}
