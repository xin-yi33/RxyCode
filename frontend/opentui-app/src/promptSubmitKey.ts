function enterName(name?: string): boolean {
  const n = (name || "").toLowerCase();
  return n === "return" || n === "linefeed" || n === "kpenter" || n === "enter";
}

/**
 * Shift+Enter / Ctrl+Enter (and Windows ConPTY LF) inserts a newline instead of sending.
 */
export function isPromptNewlineKey(key: {
  name?: string;
  sequence?: string;
  raw?: string;
  shift?: boolean;
  meta?: boolean;
  ctrl?: boolean;
  super?: boolean;
}): boolean {
  if (key.meta || key.super) return false;
  // 2026-09-23：ctrl 也算换行（用户习惯 Ctrl+Enter；此前 ctrl 被排除导致
  // Ctrl+Enter 既没换行也没发送，表现为什么都没发生）。
  if ((key.shift || key.ctrl) && enterName(key.name)) return true;
  const name = (key.name || "").toLowerCase();
  if (name === "linefeed") return true;
  const seq = key.sequence ?? key.raw ?? "";
  // Windows ConPTY 常把 Shift+Enter 的 LF 收成 CRLF。裸 CR 仍是发送。
  return seq === "\n" || seq === "\r\n" || seq === "\x1b\n";
}

/**
 * Detect Enter used to submit the chat prompt (not Shift+Enter newline).
 * Windows ConPTY may deliver return / kpenter, or only sequence \r.
 */
export function isPromptSubmitKey(key: {
  name?: string;
  sequence?: string;
  raw?: string;
  shift?: boolean;
  meta?: boolean;
  ctrl?: boolean;
  super?: boolean;
}): boolean {
  if (isPromptNewlineKey(key)) return false;
  if (key.shift || key.meta || key.ctrl || key.super) return false;
  const name = (key.name || "").toLowerCase();
  if (name === "return" || name === "kpenter" || name === "enter") {
    return true;
  }
  const seq = key.sequence ?? key.raw ?? "";
  return seq === "\r";
}

/** Trim trailing CR/LF that a prior failed Enter may have inserted. */
export function normalizePromptSubmitText(text: string): string {
  return text.replace(/[\r\n]+$/g, "").trim();
}
