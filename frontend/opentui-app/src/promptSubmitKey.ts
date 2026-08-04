/**
 * Detect Enter used to submit the chat prompt (not Shift+Enter newline).
 * Windows ConPTY may deliver return / linefeed / kpenter, or only sequence \r/\n.
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
  if (key.shift || key.meta || key.ctrl || key.super) return false;
  const name = (key.name || "").toLowerCase();
  if (name === "return" || name === "linefeed" || name === "kpenter" || name === "enter") {
    return true;
  }
  const seq = key.sequence ?? key.raw ?? "";
  return seq === "\r" || seq === "\n" || seq === "\r\n";
}

/** Trim trailing CR/LF that a prior failed Enter may have inserted. */
export function normalizePromptSubmitText(text: string): string {
  return text.replace(/[\r\n]+$/g, "").trim();
}
