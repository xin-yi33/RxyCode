import type { TextareaOptions } from "@opentui/core";

/**
 * Chat prompt keymap: Enter submits, Shift+Enter / Ctrl+Enter inserts newline.
 * OpenTUI textarea defaults to Enter=newline (see defaultTextareaKeyBindings).
 */
export const CHAT_PROMPT_KEY_BINDINGS: NonNullable<TextareaOptions["keyBindings"]> = [
  { name: "return", action: "submit" },
  { name: "kpenter", action: "submit" },
  { name: "return", shift: true, action: "newline" },
  { name: "kpenter", shift: true, action: "newline" },
  // 2026-09-23：用户习惯 Ctrl+Enter 换行；OpenTUI 默认绑定没有它，
  // 不加的话 Ctrl+Enter 会落空（无绑定→无动作）。
  { name: "return", ctrl: true, action: "newline" },
  { name: "kpenter", ctrl: true, action: "newline" },
  // Windows ConPTY often delivers Shift+Enter as LF without a shift flag.
  { name: "linefeed", action: "newline" },
  { name: "linefeed", shift: true, action: "newline" },
];
