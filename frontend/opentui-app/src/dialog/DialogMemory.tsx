/**
 * Memory manager — list / add / search / delete-with-confirm. No chat dump.
 */

import { useCallback, useEffect, useState } from "react";
import { useDialog } from "./DialogHost.tsx";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogConfirm } from "./DialogConfirm.tsx";
import { DialogPrompt } from "./DialogPrompt.tsx";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { C } from "../theme.ts";

export function DialogMemory({
  onClose,
  onMessage,
  initialQuery,
}: {
  onClose: () => void;
  onMessage: (text: string) => void;
  initialQuery?: string;
}) {
  const dialog = useDialog();
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [items, setItems] = useState<Array<{ id: string; title: string; description?: string }>>([]);

  const reload = useCallback(
    async (query?: string) => {
      setPhase("loading");
      setError("");
      const q = query ?? initialQuery;
      const cmd = q ? `/memory search ${q}` : "/memory list";
      const result = await sendCommand(cmd);
      if (!result) {
        setError("无法加载记忆");
        setItems([]);
        setPhase("error");
        return;
      }
      setItems(listFromCommandResult(result, "memory"));
      setPhase("ready");
    },
    [initialQuery],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const openAdd = () => {
    dialog.push(
      <DialogPrompt
        title="添加记忆"
        placeholder="输入要记住的内容…"
        onCancel={() => dialog.pop()}
        onSubmit={(text) => {
          void (async () => {
            if (!text) {
              dialog.pop();
              return;
            }
            const result = await sendCommand(`/memory add ${text}`);
            onMessage(String(result?.message || "记忆已添加"));
            dialog.pop();
          })();
        }}
      />,
    );
  };

  const openSearch = () => {
    dialog.push(
      <DialogPrompt
        title="搜索记忆"
        placeholder="关键词…"
        onCancel={() => dialog.pop()}
        onSubmit={(q) => {
          dialog.replace(
            <DialogMemory onClose={onClose} onMessage={onMessage} initialQuery={q || undefined} />,
          );
        }}
      />,
    );
  };

  const confirmDelete = (id: string, title: string) => {
    dialog.push(
      <DialogConfirm
        title="删除记忆"
        message={`确定删除 ${title}？`}
        confirmLabel="删除"
        danger
        onCancel={() => dialog.pop()}
        onConfirm={() => {
          void (async () => {
            const result = await sendCommand(`/memory remove ${id}`);
            onMessage(
              String(
                result?.message ||
                  (result?.action === "error" ? "删除失败" : `已删除 ${id}`),
              ),
            );
            dialog.pop();
          })();
        }}
      />,
    );
  };

  const options: DialogSelectOption<string>[] = [
    ...items.map((it) => ({
      id: it.id,
      title: it.title,
      description: it.description,
      category: "记忆",
      value: `item:${it.id}`,
    })),
    { id: "__add__", title: "+ 添加记忆", description: "写入一条新记忆", category: "操作", value: "__add__" },
    { id: "__search__", title: "搜索记忆", description: "按关键词过滤", category: "操作", value: "__search__" },
    { id: "__refresh__", title: "刷新列表", description: "重新加载", category: "操作", value: "__refresh__" },
  ];

  if (phase === "loading" && items.length === 0) {
    return (
      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor: C.borderDim,
          borderStyle: "rounded",
          paddingLeft: 1,
          backgroundColor: C.bg,
        }}
      >
        <text fg={C.text} attributes={1}>
          {" 记忆"}
        </text>
        <DialogLoading />
      </box>
    );
  }

  return (
    <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
      {phase === "error" && error ? <DialogError text={error} /> : null}
      {phase === "ready" && items.length === 0 ? (
        <DialogError text="暂无记忆 — 可用「+ 添加记忆」" />
      ) : null}
      <DialogSelect
        title={initialQuery ? `记忆 · 搜索: ${initialQuery}` : "记忆"}
        options={options}
        categoryOrder={["记忆", "操作"]}
        onClose={onClose}
        onSelect={(opt) => {
          if (opt.value === "__add__") openAdd();
          else if (opt.value === "__search__") openSearch();
          else if (opt.value === "__refresh__") void reload();
          else if (opt.value.startsWith("item:")) confirmDelete(opt.value.slice(5), opt.title);
        }}
      />
    </box>
  );
}
