import type { StreamEvent } from "../streamReducer.ts";

/** Map appserver JSON-RPC notification method + params to OpenTUI SSE-shaped events. */
export function notifyToStreamEvent(method: string, params: unknown): StreamEvent | null {
  const p = (params ?? {}) as Record<string, unknown>;
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
  }
  return null;
}
