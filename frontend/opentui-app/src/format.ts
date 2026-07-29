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

export function formatHeaderLine(mode: Mode, model: string, thinkingLive: boolean): string {
  const base = `RxyCode v1.2.0 · ${mode} · ${model}`;
  return thinkingLive ? `${base} · 思考中` : base;
}

export function formatInputHint(isStreaming: boolean): string {
  return isStreaming ? "Processing..." : "Ready";
}

export function messageFg(role: ChatMessage["role"]): string {
  switch (role) {
    case "user":
      return "#FFB6C1";
    case "assistant":
      return "#ffffff";
    case "thinking":
      return "#555555";
    case "tool":
      return "#aaaaaa";
    case "system":
      return "#f9e2af";
    default:
      return "#ffffff";
  }
}
