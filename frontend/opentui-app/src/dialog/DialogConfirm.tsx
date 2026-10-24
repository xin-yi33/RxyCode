/**
 * Confirm layer — push on top of a domain list; Esc/取消 → onCancel (pop).
 */

import { useKeyboard } from "@opentui/react";
import { C } from "../theme.ts";
import { SELECT_BG, SELECT_FG } from "./colors.ts";

export function DialogConfirm({
  title = "确认",
  message,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useKeyboard((key) => {
    if (key.name === "escape") {
      key.preventDefault?.();
      onCancel();
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      onConfirm();
      return;
    }
    if (key.name === "y") {
      key.preventDefault?.();
      onConfirm();
      return;
    }
    if (key.name === "n") {
      key.preventDefault?.();
      onCancel();
    }
  });

  const confirmFg = danger ? C.yellow : SELECT_FG;

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: danger ? C.yellow : C.borderDim,
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
      <box style={{ width: "100%", height: 1 }}>
        <text fg={C.subtext}>{`  ${message}`}</text>
      </box>
      <box style={{ flexDirection: "row", width: "100%", height: 1, marginTop: 0 }}>
        <text fg={confirmFg} bg={SELECT_BG}>
          {` ↵ ${confirmLabel} `}
        </text>
        <text fg={C.overlay2}>{`  esc ${cancelLabel}  (y/n)`}</text>
      </box>
    </box>
  );
}
