/**
 * Shared empty / error / loading rows for dialogs (no business logic).
 */

import { C } from "../theme.ts";

export function DialogLoading({ text = "加载中…" }: { text?: string }) {
  return (
    <box style={{ height: 1, width: "100%", paddingLeft: 1 }}>
      <text fg={C.overlay2}>{`  ${text}`}</text>
    </box>
  );
}

export function DialogEmpty({ text = "暂无条目" }: { text?: string }) {
  return (
    <box style={{ height: 1, width: "100%", paddingLeft: 1 }}>
      <text fg={C.overlay2}>{`  ${text}`}</text>
    </box>
  );
}

export function DialogError({ text }: { text: string }) {
  return (
    <box style={{ height: 1, width: "100%", paddingLeft: 1 }}>
      <text fg={C.yellow}>{`  ⚠ ${text}`}</text>
    </box>
  );
}
