/**
 * Pure command classification — slash input never enters /chat/stream.
 */

import { isSlashCommand, LOCAL_COMMAND_NAMES } from "./commands.ts";

export type ClassifiedInput =
  | { kind: "command"; name: string; args: string; raw: string; local: boolean }
  | { kind: "chat"; text: string };

export function classifyInput(raw: string): ClassifiedInput {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: "chat", text: "" };
  if (!isSlashCommand(trimmed)) return { kind: "chat", text: trimmed };

  const firstSpace = trimmed.search(/\s/);
  const name = firstSpace < 0 ? trimmed : trimmed.slice(0, firstSpace);
  const args = firstSpace < 0 ? "" : trimmed.slice(firstSpace).trim();
  const localName = name.toLowerCase();
  // Multi-word local? none. /memory list goes to API.
  return {
    kind: "command",
    name: localName,
    args,
    raw: trimmed,
    local: LOCAL_COMMAND_NAMES.has(localName),
  };
}

export function formatCommandResult(data: Record<string, unknown> | null, fallbackCmd: string): string {
  if (!data) return `命令失败: ${fallbackCmd}`;
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  if (typeof data.error === "string" && data.error.trim()) return data.error;
  if (typeof data.action === "string") {
    const extra = typeof data.message === "string" ? data.message : JSON.stringify(data);
    return `[${data.action}] ${extra}`;
  }
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}
