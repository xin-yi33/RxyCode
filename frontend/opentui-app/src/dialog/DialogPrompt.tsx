/**
 * Single-line prompt layer for dialog wizards (push on stack).
 *
 * Visible native <input> owns the caret (left/right/home/end/mouse).
 * Do not intercept printable/backspace — that pinned the cursor at the end.
 */

import { useEffect, useRef, useState } from "react";
import { appendFileSync } from "node:fs";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import { C } from "../theme.ts";
import { SELECT_BG } from "./colors.ts";

export function DialogPrompt({
  title,
  placeholder,
  initial = "",
  mask = false,
  hint,
  onSubmit,
  onCancel,
}: {
  title: string;
  placeholder: string;
  initial?: string;
  /** Legacy prop — credentials are shown in plaintext for correct caret UX. */
  mask?: boolean;
  /** Optional dim footer line, e.g. an HTTPS reminder. */
  hint?: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  void mask;
  const [draft, setDraft] = useState(initial);
  const focusRef = useRef<InputRenderable>(null);

  useEffect(() => {
    setDraft(initial);
    try {
      focusRef.current?.focus();
      if (focusRef.current) {
        focusRef.current.value = initial;
      }
    } catch {
      /* */
    }
  }, [initial, title]);

  useKeyboard((key) => {
    const name = key.name || "";
    if (name === "escape") {
      key.preventDefault?.();
      onCancel();
    }
  });

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: C.borderDim,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
        <text fg={C.text} attributes={1}>
          {" "}
          {title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </box>
      <box style={{ flexDirection: "row", height: 1, width: "100%" }}>
        <input
          ref={focusRef}
          focused
          value={draft}
          placeholder={placeholder}
          cursorColor={SELECT_BG}
          onInput={(v) => setDraft(String(v ?? ""))}
          onSubmit={(v) => onSubmit(String(v ?? draft).trim())}
          style={{
            flexGrow: 1,
            height: 1,
            backgroundColor: C.bg,
          }}
        />
      </box>
      {hint ? (
        <box style={{ height: 1, width: "100%" }}>
          <text fg={C.overlay2}>
            {"  "}
            {hint}
          </text>
        </box>
      ) : null}
    </box>
  );
}
