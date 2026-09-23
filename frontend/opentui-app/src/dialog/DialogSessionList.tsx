/**
 * OpenTUI session picker. Catalog RPC is sessions/list.
 * Enter calls attachSession (stdio), not the slash session command.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useKeyboard } from "@opentui/react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogPrompt } from "./DialogPrompt.tsx";
import { C } from "../theme.ts";
import { getChatTransport } from "../chatApi.ts";
import {
  applySessionListKey,
  SESSION_LIST_FOOTER_ITEMS,
  SESSION_RENAME_SUCCESS,
  promoteSessionRow,
} from "./sessionListKeybind.ts";
import type { SessionListRow } from "../transport/types.ts";

const DATE_GROUP_PINNED = "Pinned";
const DATE_GROUP_TODAY = "Today";
const DATE_GROUP_YESTERDAY = "Yesterday";

function visibleRows(rows: SessionListRow[]): SessionListRow[] {
  return rows.filter((row) => !row.trashed_at && !row.parent_session_id);
}

function categoryOrderOf(rows: SessionListRow[]): string[] {
  const seen: string[] = [];
  const bump = (name: string) => {
    if (name && !seen.includes(name)) seen.push(name);
  };
  bump(DATE_GROUP_PINNED);
  bump(DATE_GROUP_TODAY);
  bump(DATE_GROUP_YESTERDAY);
  for (const row of rows) bump(row.date_group || DATE_GROUP_TODAY);
  return seen;
}

export function DialogSessionList({
  onClose,
  onLoaded,
}: {
  onClose: () => void;
  onLoaded: (payload: { name: string; messages?: unknown[]; message?: string }) => void;
}) {
  const [rows, setRows] = useState<SessionListRow[] | null>(null);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState<SessionListRow | null>(null);
  const [busy, setBusy] = useState("");
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const transport = getChatTransport();
    const listed = await transport.listSessions();
    const next = visibleRows(listed);
    setRows(next);
    if (!next.length) setError("暂无会话");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setRows([]);
      }
    })();
  }, [reload]);

  const options: DialogSelectOption<SessionListRow>[] = useMemo(() => {
    return (rows || []).map((row) => ({
      id: row.session_id,
      title: row.display_title || row.title || "新任务",
      footer: row.age_label || "",
      category: row.date_group || DATE_GROUP_TODAY,
      value: row,
    }));
  }, [rows]);

  const categoryOrder = useMemo(() => categoryOrderOf(rows || []), [rows]);

  useKeyboard((key) => {
    if (key.name === "escape" && rows !== null && rows.length === 0) {
      key.preventDefault?.();
      onClose();
    }
  });

  if (renaming) {
    return (
      <DialogPrompt
        title="重命名会话"
        placeholder={renaming.display_title || renaming.title || "新任务"}
        initial={renaming.display_title || renaming.title || ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(text) => {
          void (async () => {
            const title = text.trim();
            if (!title) {
              setRenaming(null);
              return;
            }
            const sessionId = renaming.session_id;
            try {
              const updated = (await getChatTransport().renameSession(sessionId, title)) || {
                session_id: sessionId,
              };
              const patch = {
                title: updated.title || title,
                display_title: updated.display_title || title,
                age_label: updated.age_label || "now",
                date_group: updated.date_group || DATE_GROUP_TODAY,
                updated_at: updated.updated_at,
                title_is_manual: true,
              };
              setRows((prev) => promoteSessionRow(prev || [], sessionId, patch));
              setHighlightId(sessionId);
              setBusy(SESSION_RENAME_SUCCESS);
              setRenaming(null);
              await reload();
            } catch (err) {
              setBusy(err instanceof Error ? err.message : String(err));
              setRenaming(null);
            }
          })();
        }}
      />
    );
  }

  if (rows === null) {
    return (
      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor: C.borderDim,
          borderStyle: "rounded",
          paddingLeft: 1,
          height: 3,
        }}
      >
        <text fg={C.text} attributes={1}>
          {" 切换会话"}
        </text>
        <text fg={C.overlay2}>{" 加载中…"}</text>
      </box>
    );
  }

  if (rows.length === 0) {
    return (
      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor: C.borderDim,
          borderStyle: "rounded",
          paddingLeft: 1,
          height: 4,
        }}
      >
        <text fg={C.text} attributes={1}>
          {" 切换会话"}
        </text>
        <text fg={C.overlay2}>
          {"  "}
          {error || "暂无会话"}
        </text>
        <text fg={C.overlay2}>{"  esc 关闭"}</text>
      </box>
    );
  }

  return (
    <DialogSelect
      title="切换会话"
      options={options}
      categoryOrder={categoryOrder}
      placeholder="搜索会话"
      currentId={highlightId || undefined}
      footerHint={busy}
      footerHintItems={SESSION_LIST_FOOTER_ITEMS}
      onClose={onClose}
      onSelect={(opt) => {
        void (async () => {
          try {
            const attached = await getChatTransport().attachSession(opt.value.session_id);
            onLoaded({
              name: opt.value.display_title || opt.value.session_id,
              messages: attached.messages,
              message: `已加载会话: ${opt.value.display_title || opt.value.session_id}`,
            });
            onClose();
          } catch (err) {
            setBusy(err instanceof Error ? err.message : String(err));
          }
        })();
      }}
      onKeybind={(key, opt) => {
        const result = applySessionListKey(key, {
          pendingDeleteId: null,
          selectedId: opt.id,
        });
        if (result.action === "none") return false;
        if (result.action === "close") {
          onClose();
          return true;
        }
        // 自动会话列表不提供手动删除（原 ctrl+d → session/trash）。
        // if (result.action === "delete-pending") {
        //   setPendingDeleteId(result.nextPendingDeleteId);
        //   return true;
        // }
        // if (result.action === "delete-confirm") {
        //   void getChatTransport().trashSession(opt.value.session_id).then(reload);
        //   return true;
        // }
        if (result.action === "rename") {
          setRenaming(opt.value);
          return true;
        }
        if (result.action === "pin") {
          void (async () => {
            await getChatTransport().pinSession(opt.value.session_id, !opt.value.pinned);
            await reload();
          })();
          return true;
        }
        if (result.action === "fork") {
          void (async () => {
            await getChatTransport().forkSession(opt.value.session_id);
            await reload();
          })();
          return true;
        }
        return false;
      }}
    />
  );
}
