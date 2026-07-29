/**
 * Single-line prompt layer for dialog wizards (push on stack).
 */

import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import { C } from "../theme.ts";
import { SELECT_BG, SELECT_FG } from "./colors.ts";
import { textFromKeyEvent } from "./DialogSelect.tsx";

export function DialogPrompt({
  title,
  placeholder,
  initial = "",
  onSubmit,
  onCancel,
}: {
  title: string;
  placeholder: string;
  initial?: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const focusRef = useRef<InputRenderable>(null);

  useEffect(() => {
    try {
      focusRef.current?.focus();
      if (focusRef.current) focusRef.current.value = initial;
    } catch {
      /* */
    }
  }, [initial]);

  useKeyboard((key) => {
    if (key.name === "escape") {
      key.preventDefault?.();
      onCancel();
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      onSubmit(draft.trim());
      return;
    }
    if (key.name === "backspace" || key.name === "delete") {
      key.preventDefault?.();
      setDraft((d) => {
        const next = d.slice(0, -1);
        try {
          if (focusRef.current) focusRef.current.value = next;
        } catch {
          /* */
        }
        return next;
      });
      return;
    }
    const parsed = textFromKeyEvent(key);
    if (!parsed) return;
    if (parsed.text) {
      key.preventDefault?.();
      setDraft((d) => {
        const next = d + parsed.text;
        try {
          if (focusRef.current) focusRef.current.value = next;
        } catch {
          /* */
        }
        return next;
      });
    }
    if (parsed.submit) {
      key.preventDefault?.();
      onSubmit((draft + (parsed.text || "")).trim());
    }
  });

  const shown = draft || placeholder;

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: C.primary,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
        <text fg={C.primary} attributes={1}>
          {" "}
          {title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </box>
      <box style={{ flexDirection: "row", height: 1, width: "100%" }}>
        <text fg={C.primary}>{"> "}</text>
        <text fg={SELECT_FG} bg={draft ? undefined : SELECT_BG}>
          {shown.slice(0, 1) || " "}
        </text>
        <text fg={draft ? C.text : C.overlay2}>{shown.slice(1)}</text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <input
          ref={focusRef}
          focused
          onInput={(v) => setDraft(String(v ?? ""))}
          onSubmit={() => onSubmit(draft.trim())}
          style={{ position: "absolute", width: 0, height: 0, left: 0, top: 0 }}
        />
      </box>
    </box>
  );
}
