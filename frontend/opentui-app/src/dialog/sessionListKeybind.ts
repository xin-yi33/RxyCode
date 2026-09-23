export const SESSION_LIST_KEY_RENAME = "ctrl+r";
export const SESSION_LIST_KEY_DELETE = "ctrl+d";
export const SESSION_LIST_KEY_PIN = "ctrl+f";
export const SESSION_LIST_KEY_FORK = "ctrl+shift+f";
export const SESSION_LIST_PENDING_DELETE = "Press ctrl+d again to confirm";
// 原底栏含 delete ctrl+d；自动会话列表不再提供手动删除。
export const SESSION_LIST_FOOTER =
  " pin/unpin ctrl+f    rename ctrl+r    fork ctrl+shift+f";
export const SESSION_LIST_FOOTER_ITEMS: Array<{ label: string; keys: string }> = [
  { label: "pin/unpin", keys: "ctrl+f" },
  { label: "rename", keys: "ctrl+r" },
  { label: "fork", keys: "ctrl+shift+f" },
];
export const SESSION_RENAME_SUCCESS = "rename successful";

export function promoteSessionRow<T extends { session_id: string }>(
  rows: T[],
  sessionId: string,
  patch: Partial<T>,
): T[] {
  const next = rows.map((row) =>
    row.session_id === sessionId ? { ...row, ...patch } : row,
  );
  const idx = next.findIndex((row) => row.session_id === sessionId);
  if (idx <= 0) return next;
  const [item] = next.splice(idx, 1);
  next.unshift(item);
  return next;
}

export type SessionListKeyState = {
  pendingDeleteId: string | null;
  selectedId: string | null;
};

export type SessionListKeyAction =
  | "rename"
  | "delete-pending"
  | "delete-confirm"
  | "pin"
  | "fork"
  | "close"
  | "none";

export type SessionListKeyResult = {
  action: SessionListKeyAction;
  nextPendingDeleteId: string | null;
};

export function applySessionListKey(
  key: { ctrl?: boolean; shift?: boolean; name?: string },
  state: SessionListKeyState,
): SessionListKeyResult {
  const name = (key.name || "").toLowerCase();
  if (name === "escape") {
    return { action: "close", nextPendingDeleteId: null };
  }
  if (key.ctrl && key.shift && name === "f") {
    return { action: "fork", nextPendingDeleteId: null };
  }
  if (key.ctrl && name === "r") {
    return { action: "rename", nextPendingDeleteId: null };
  }
  // 自动会话不提供手动删除：ctrl+d 不再进入 pending / trash。
  // if (key.ctrl && name === "d") {
  //   if (state.pendingDeleteId && state.pendingDeleteId === state.selectedId) {
  //     return { action: "delete-confirm", nextPendingDeleteId: null };
  //   }
  //   return { action: "delete-pending", nextPendingDeleteId: state.selectedId };
  // }
  if (key.ctrl && name === "d") {
    return { action: "none", nextPendingDeleteId: null };
  }
  if (key.ctrl && name === "f") {
    return { action: "pin", nextPendingDeleteId: null };
  }
  return { action: "none", nextPendingDeleteId: state.pendingDeleteId };
}
