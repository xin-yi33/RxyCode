import type { StreamEvent } from "../streamReducer.ts";

/** Map appserver JSON-RPC notification method + params to OpenTUI SSE-shaped events. */
export function notifyToStreamEvent(method: string, params: unknown): StreamEvent | null {
  const p = (params ?? {}) as Record<string, unknown>;
  const payload = (p.payload ?? {}) as Record<string, unknown>;
  switch (method) {
    case "event/message_delta":
      return { type: "token", text: String(p.text ?? "") };
    case "event/progress":
      return { type: "progress", message: String(p.text ?? ""), text: String(p.text ?? "") };
    case "event/reasoning_snapshot":
      return {
        type: "reasoning",
        thinking: String(p.text ?? ""),
        snapshot: Boolean(p.snapshot),
      };
    case "event/tool_begin":
      return {
        type: "tool_call",
        name: String(p.tool_name ?? "tool"),
        args: p.arguments as string | Record<string, unknown> | undefined,
      };
    case "event/tool_end":
      return {
        type: "tool_result",
        name: String(p.tool_name ?? ""),
        result: String(p.summary ?? ""),
        status: p.ok === false ? "error" : "success",
      };
    case "event/final":
      return {
        type: "final",
        text: String(p.text ?? ""),
        message: String(p.text ?? ""),
      };
    case "event/done":
      return { type: "done" };
    case "event/error":
      return {
        type: "error",
        error: String(p.message ?? p.text ?? "error"),
        message: String(p.message ?? p.text ?? "error"),
      };
    /* ── Phase B: child_session/* events ─────────────────── */
    case "child_session/created":
      return {
        type: "child_created",
        childSessionId: String(p.session_id ?? ""),
        parentSessionId: String(p.parent_session_id ?? ""),
        agentId: String(p.agent_id ?? payload.agent_id ?? ""),
        text: String(p.summary ?? `子代理 ${p.agent_id ?? ""} 已创建`),
      };
    case "child_session/status":
      return {
        type: "child_status",
        childSessionId: String(p.session_id ?? ""),
        childStatus: String(p.status ?? payload.status ?? "unknown"),
        text: String(p.summary ?? ""),
        agentId: String(p.agent_id ?? payload.agent_id ?? ""),
      };
    case "child_session/completed":
      return {
        type: "child_completed",
        childSessionId: String(p.session_id ?? ""),
        childStatus: "completed",
        text: String(p.summary ?? payload.summary ?? "子代理执行完成"),
        usage: payload.usage as Record<string, unknown> | undefined,
      };
    case "child_session/error":
      return {
        type: "child_error",
        childSessionId: String(p.session_id ?? ""),
        childStatus: "failed",
        text: String(payload.message ?? p.summary ?? "error"),
        error: String(payload.message ?? "子代理执行错误"),
      };
  }
  return null;
}
