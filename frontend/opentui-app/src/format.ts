import type { ChatMessage, Mode } from "./types.ts";

export function formatMessageLine(msg: ChatMessage): string {
  switch (msg.role) {
    case "user":
      return `> ${msg.content}`;
    case "assistant":
      return msg.content;
    case "thinking":
      return `思考: ${msg.content}`;
    case "tool":
      return `⚙ ${msg.toolName || "tool"} [${msg.toolStatus || "running"}]`;
    case "system":
      return `• ${msg.content}`;
    default:
      return msg.content;
  }
}

export const APP_VERSION = "1.4.0";

export function formatHeaderLine(mode: Mode, model: string, thinkingLive: boolean): string {
  // 三参签名锁定（UPDATE-01 U54）。顶栏芯片走 App.tsx JSX，不再渲染本字符串。
  const base = `RxyCode v${APP_VERSION} · ${mode} · ${model}`;
  return thinkingLive ? `${base} · 思考中` : base;
}

// 废弃代码（2026-09-21）：formatHeaderLine 曾作为顶栏唯一文案。禁止改成四参塞 effort 芯片。

const THOUGHT_PLACEHOLDERS = new Set(["", "…", "...", "思考中...", "思考中…", "Done", "正在思考中...", "已思考完毕"]);

export function hasThinkingChain(content: string): boolean {
  return !THOUGHT_PLACEHOLDERS.has((content || "").trim());
}

export function shouldRenderThought(msg: ChatMessage): boolean {
  // Hide only a settled boot placeholder ("…" / "思考中..."). A Thought that
  // already has a real chain must stay in the list after it finishes.
  // 废弃代码（2026-09-22）：done===true 就整张卡片不渲染。首位 Thought
  // 思考完后从对话里消失。禁止再按 done 隐藏有正文的 Thought。
  if (msg.role !== "thinking") return true;
  if (msg.done !== true) return true;
  return hasThinkingChain(msg.content);
}

export function formatInputHint(isStreaming: boolean, queued = 0): string {
  if (!isStreaming) {
    return queued > 0 ? `Ready · 队列 ${queued}` : "Ready";
  }
  return queued > 0 ? `思考中 · 队列 ${queued}` : "思考中";
}

/**
 * 2026-09-23: local ticking elapsed suffix for the progress slot.  Backend
 * heartbeats can stall (emit failure / pipe stall) while the build keeps
 * running — the frozen status line made the TUI look dead (用户报告：log 在
 * 跑，界面不像在跑).  Appending this locally-ticked suffix guarantees the
 * status line changes every second while streaming, independent of backend
 * heartbeats.  Returns "" when not applicable.
 */
export function formatElapsedSuffix(elapsedSec: number | null): string {
  if (elapsedSec == null || !Number.isFinite(elapsedSec) || elapsedSec < 0) {
    return "";
  }
  const total = Math.floor(elapsedSec);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return mins >= 1 ? ` · ${mins}m${secs}s` : ` · ${secs}s`;
}

export function messageFg(role: ChatMessage["role"]): string {
  switch (role) {
    case "user":
      return "#FFB6C1";
    case "assistant":
      return "#ffffff";
    case "thinking":
      return "#aaaaaa";
    case "tool":
      return "#aaaaaa";
    case "system":
      return "#f9e2af";
    default:
      return "#ffffff";
  }
}
