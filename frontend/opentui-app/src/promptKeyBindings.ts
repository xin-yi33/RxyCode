import type { TextareaOptions } from "@opentui/core";

/**
 * Chat prompt keymap: Enter submits, Shift+Enter inserts newline.
 * OpenTUI textarea defaults to Enter=newline (see defaultTextareaKeyBindings).
 */
export const CHAT_PROMPT_KEY_BINDINGS: NonNullable<TextareaOptions["keyBindings"]> = [
  { name: "return", action: "submit" },
  { name: "kpenter", action: "submit" },
  { name: "linefeed", action: "submit" },
  { name: "return", shift: true, action: "newline" },
  { name: "kpenter", shift: true, action: "newline" },
  { name: "linefeed", shift: true, action: "newline" },
];
