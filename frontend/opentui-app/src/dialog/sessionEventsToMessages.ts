import type { ChatMessage, Mode, ToolStatus } from "../types.ts";
import { validateClipboardAttachments } from "../clipboard.ts";

export type SessionEventLike = {
  method?: string;
  params?: Record<string, unknown> | null;
  ts?: string | number;
};

function eventTime(ev: SessionEventLike, fallback: number): number {
  const raw = ev.ts ?? ev.params?.ts;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw < 1e12 ? raw * 1000 : raw;
  }
  if (typeof raw === "string" && raw.trim()) {
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return fallback;
}

function detachOpen(openOrder: ChatMessage[], row: ChatMessage): void {
  const index = openOrder.lastIndexOf(row);
  if (index >= 0) openOrder.splice(index, 1);
}

function takeOpenTool(
  openByCall: Map<string, ChatMessage>,
  openOrder: ChatMessage[],
  callId: string,
  toolName: string,
): ChatMessage | undefined {
  if (callId) {
    const matched = openByCall.get(callId);
    if (matched && matched.toolStatus === "running") {
      openByCall.delete(callId);
      detachOpen(openOrder, matched);
      return matched;
    }
  }
  for (let index = openOrder.length - 1; index >= 0; index -= 1) {
    const candidate = openOrder[index];
    if (!candidate || candidate.toolStatus !== "running") continue;
    if (callId && candidate.toolCallId) {
      if (candidate.toolCallId !== callId) continue;
    } else if (toolName && candidate.toolName !== toolName) {
      continue;
    }
    if (candidate.toolCallId) openByCall.delete(candidate.toolCallId);
    openOrder.splice(index, 1);
    return candidate;
  }
  return undefined;
}

export function sessionEventsToMessages(events: SessionEventLike[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const openByCall = new Map<string, ChatMessage>();
  const openOrder: ChatMessage[] = [];
  let buf = "";
  const stamp = Date.now();

  const push = (
    role: ChatMessage["role"],
    content: string,
    extra?: Partial<ChatMessage>,
    at?: number,
  ): ChatMessage => {
    const row: ChatMessage = {
      id: `sess-${messages.length}-${stamp}`,
      role,
      content,
      timestamp: at ?? stamp + messages.length,
      done: true,
      live: false,
      ...extra,
    };
    messages.push(row);
    return row;
  };

  const flushAssistant = (at?: number) => {
    if (!buf) return;
    push("assistant", buf, { done: true, live: false }, at);
    buf = "";
  };

  for (const ev of events) {
    const method = String(ev.method || "");
    const p = (ev.params || {}) as Record<string, unknown>;
    const at = eventTime(ev, stamp + messages.length);
    if (method === "session/prompt" || method === "event/user_message") {
      flushAssistant(at);
      const text = String(p.text ?? p.content ?? "");
      if (text) {
        let attachments: ChatMessage["attachments"];
        try {
          attachments = validateClipboardAttachments(p.attachments);
        } catch {
          // Historical events have no attachment field; malformed metadata is
          // ignored as one unit and never copied into transcript state.
          attachments = undefined;
        }
        push("user", text, attachments?.length ? { attachments } : {}, at);
      }
      continue;
    }
    if (method === "event/message_delta") {
      buf += String(p.text ?? "");
      continue;
    }
    if (method === "event/final") {
      const thought = String(p.thinking ?? "").trim();
      if (thought) {
        push("thinking", thought, { done: true, live: false, expanded: true, hasReasoning: true }, at);
      }
      const text = String(p.text ?? buf);
      buf = "";
      if (text) push("assistant", text, { done: true, live: false }, at);
      continue;
    }
    if (method === "event/reasoning_snapshot") {
      const text = String(p.text ?? "");
      if (text) push("thinking", text, { done: true, live: false, expanded: true, hasReasoning: true }, at);
      continue;
    }
    if (method === "event/error") {
      flushAssistant(at);
      const text = String(p.message ?? p.text ?? "");
      if (text) push("system", text, { done: true }, at);
      continue;
    }
    if (method === "event/tool_begin") {
      flushAssistant(at);
      const args = p.arguments;
      const callId = String(p.call_id ?? "");
      const row = push(
        "tool",
        "",
        {
          toolName: String(p.tool_name ?? "tool"),
          toolCallId: callId,
          toolStatus: "running",
          toolArgs: typeof args === "string" ? args : args != null ? JSON.stringify(args) : "",
          toolExpanded: true,
        },
        at,
      );
      openOrder.push(row);
      if (callId) openByCall.set(callId, row);
      continue;
    }
    if (method === "event/tool_end") {
      const callId = String(p.call_id ?? "");
      const toolName = String(p.tool_name ?? "");
      const status: ToolStatus = p.ok === false ? "error" : "success";
      const existing = takeOpenTool(openByCall, openOrder, callId, toolName);
      if (existing) {
        existing.content = String(p.summary ?? existing.content);
        existing.toolStatus = status;
        existing.endedAt = at;
        existing.toolExpanded = true;
        existing.done = true;
        existing.live = false;
      } else {
        push(
          "tool",
          String(p.summary ?? ""),
          {
            toolName: toolName || "tool",
            toolCallId: callId,
            toolStatus: status,
            endedAt: at,
            toolExpanded: true,
          },
          at,
        );
      }
    }
  }
  flushAssistant();
  for (const msg of messages) {
    if (msg.role === "tool" && msg.toolStatus === "running") {
      msg.toolStatus = "cancelled";
      msg.endedAt = msg.endedAt ?? msg.timestamp;
      msg.live = false;
      msg.done = true;
    }
    if (msg.role === "assistant") {
      msg.done = true;
      msg.live = false;
    }
    if (msg.role === "thinking") {
      msg.done = true;
      msg.live = false;
    }
  }
  return messages;
}

const ROLES: ChatMessage["role"][] = [
  "user",
  "assistant",
  "system",
  "thinking",
  "tool",
  "child_session",
];

/** History restore must keep toolStatus/done/toolArgs. Stripping them leaves tools spinning and Markdown as source. */
export function normalizeLoadedMessages(raw: unknown[]): ChatMessage[] {
  const stamp = Date.now();
  return raw.map((m, i) => {
    const row = (m || {}) as Partial<ChatMessage> & { text?: string };
    const roleRaw = String(row.role || "assistant");
    const role: ChatMessage["role"] = (ROLES as string[]).includes(roleRaw)
      ? (roleRaw as ChatMessage["role"])
      : "system";
    const timestamp = typeof row.timestamp === "number" ? row.timestamp : stamp + i;
    const toolStatus: ToolStatus | undefined =
      role === "tool"
        ? row.toolStatus && row.toolStatus !== "running"
          ? row.toolStatus
          : "success"
        : row.toolStatus;
    return {
      id: row.id || `loaded-${i}-${stamp}`,
      role,
      content: String(row.content ?? row.text ?? ""),
      attachments: (() => {
        try {
          const attachments = validateClipboardAttachments(row.attachments);
          return attachments.length ? attachments : undefined;
        } catch {
          return undefined;
        }
      })(),
      timestamp,
      done: row.done ?? true,
      live: false,
      mode: row.mode as Mode | undefined,
      toolName: row.toolName,
      toolCallId: row.toolCallId,
      toolStatus,
      toolArgs: row.toolArgs,
      toolExpanded: row.toolExpanded,
      endedAt: row.endedAt ?? (role === "tool" ? timestamp : undefined),
      expanded: row.expanded,
      hasReasoning: row.hasReasoning,
      childSessionId: row.childSessionId,
      childStatus: row.childStatus,
      parentSessionId: row.parentSessionId,
      agentId: row.agentId,
      depth: row.depth,
    };
  });
}
