import type { StreamEvent } from "../streamReducer.ts";

export function toolWaitText(name: string, elapsedSec?: number): string {
  const key = String(name || "tool").trim() || "tool";
  const lowered = key.toLowerCase();
  const label =
    lowered === "bash" || lowered === "shell"
      ? "等待终端返回…"
      : lowered === "vision"
        ? "等待视觉识别返回…"
        : `等待工具 ${key} 返回…`;
  if (elapsedSec != null && elapsedSec >= 1) {
    return `${label.replace(/…$/, "")}（${elapsedSec}s）…`;
  }
  return label;
}

const NOISY_LIVE = /^(模型输出中|Generating\.\.\.|Analyzing your request|思考中（第)/i;

/** Yellow status text for the live spinner. Routing labels stay out. */
export function liveProgressText(event: StreamEvent): string | null {
  if (event.type === "tool_call" && event.name) {
    const key = String(event.name).trim().toLowerCase().replace(/-/g, "_");
    if (key === "final_answer") return null;
    return toolWaitText(event.name);
  }
  if (event.type === "reasoning") {
    // Real chain chunks are 1–8 chars. Never put them on the status line or
    // "思考中" flickers through every token.
    return String(event.thinking || event.text || "").trim() ? "思考中…" : null;
  }
  if (event.type !== "progress") return null;
  const text = String(event.message || event.text || "").trim();
  if (!text || /^mode=/.test(text)) return null;
  if (/正在等待模型响应|Waiting for model response/i.test(text)) return null;
  if (NOISY_LIVE.test(text)) return null;
  if (/正在连接模型|等待模型首包/.test(text)) return "等待模型返回…";
  if (text === "思考中..." || text === "思考中…") return "思考中…";
  return text;
}

/** Map appserver JSON-RPC notification method + params to OpenTUI SSE-shaped events. */
export function notifyToStreamEvent(method: string, params: unknown): StreamEvent | null {
  const p = (params ?? {}) as Record<string, unknown>;
  const payload = (p.payload ?? {}) as Record<string, unknown>;
  switch (method) {
    case "event/message_delta":
      return {
        type: "token",
        text: String(p.text ?? ""),
        intermediate: p.intermediate === true,
      };
    case "event/progress":
      return {
        type: "progress",
        message: String(p.text ?? ""),
        text: String(p.text ?? ""),
        intermediate: p.intermediate === true,
      };
    case "event/team": {
      const role = String(p.role ?? "");
      const stage = String(p.stage ?? "");
      const label = role && stage ? `[${role}] ${stage}` : role || stage;
      return { type: "progress", message: label, text: label };
    }
    case "event/agent_routed": {
      const payload = (p.payload ?? {}) as Record<string, unknown>;
      const mode = String(payload.mode ?? p.mode ?? "");
      const reason = String(p.routing_reason ?? "");
      const label = [mode && `mode=${mode}`, reason].filter(Boolean).join(" ");
      return { type: "progress", message: label, text: label, routed: true };
    }
    case "event/reasoning_snapshot":
      return {
        type: "reasoning",
        thinking: String(p.text ?? ""),
        snapshot: Boolean(p.snapshot),
        intermediate: p.intermediate === true,
      };
    case "event/tool_begin":
      return {
        type: "tool_call",
        name: String(p.tool_name ?? "tool"),
        call_id: String(p.call_id ?? ""),
        args: p.arguments as string | Record<string, unknown> | undefined,
      };
    case "event/tool_end":
      return {
        type: "tool_result",
        name: String(p.tool_name ?? ""),
        call_id: String(p.call_id ?? ""),
        result: String(p.summary ?? ""),
        status: p.ok === false ? "error" : "success",
      };
    case "event/final":
      return {
        type: "final",
        text: String(p.text ?? ""),
        message: String(p.text ?? ""),
        thinking: p.thinking != null ? String(p.thinking) : undefined,
        input_tokens: p.input_tokens as number | null | undefined,
        output_tokens: p.output_tokens as number | null | undefined,
        cache_hit_tokens: p.cache_hit_tokens as number | null | undefined,
        cache_hit_rate: p.cache_hit_rate as number | null | undefined,
        reporting_status: p.reporting_status as string | undefined,
      };
    case "event/done":
      return { type: "done" };
    case "event/error":
      return {
        type: "error",
        error: String(p.message ?? p.text ?? "error"),
        message: String(p.message ?? p.text ?? "error"),
      };
    case "event/token_usage":
    case "event/agent_usage":
      return {
        type: "token_usage",
        input_tokens: p.input_tokens as number | null | undefined,
        output_tokens: p.output_tokens as number | null | undefined,
        cache_hit_tokens: p.cache_hit_tokens as number | null | undefined,
        cache_hit_rate: p.cache_hit_rate as number | null | undefined,
        reporting_status: p.reporting_status as string | undefined,
        ...(p.context_used != null ? { context_used: p.context_used as number } : {}),
      };
    case "event/plan": {
      const steps = Array.isArray(p.steps) ? p.steps.map((item) => String(item)) : [];
      return {
        type: "plan",
        steps,
        text: steps.join("\n"),
        message: steps.join("\n"),
      };
    }
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
