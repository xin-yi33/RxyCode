/**
 * MCP manager — list / add / remove-with-confirm.
 */

import { useCallback, useEffect, useState } from "react";
import { useDialog } from "./DialogHost.tsx";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogConfirm } from "./DialogConfirm.tsx";
import { DialogPrompt } from "./DialogPrompt.tsx";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { C } from "../theme.ts";

export function DialogMcp({
  onClose,
  onMessage,
}: {
  onClose: () => void;
  onMessage: (text: string) => void;
}) {
  const dialog = useDialog();
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [items, setItems] = useState<Array<{ id: string; title: string; description?: string }>>([]);

  const reload = useCallback(async () => {
    setPhase("loading");
    setError("");
    const result = await sendCommand("/list-mcp");
    if (!result) {
      setError("无法加载 MCP");
      setItems([]);
      setPhase("error");
      return;
    }
    setItems(listFromCommandResult(result, "mcp"));
    setPhase("ready");
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openAdd = () => {
    dialog.push(
      <DialogPrompt
        title="添加 MCP"
        placeholder="name command [args…]"
        onCancel={() => dialog.pop()}
        onSubmit={(text) => {
          void (async () => {
            if (!text) {
              dialog.pop();
              return;
            }
            const result = await sendCommand(`/addmcp ${text}`);
            onMessage(String(result?.message || "MCP 已添加"));
            dialog.pop();
          })();
        }}
      />,
    );
  };

  const confirmDelete = (id: string, title: string) => {
    dialog.push(
      <DialogConfirm
        title="删除 MCP"
        message={`确定删除 ${title}？`}
        confirmLabel="删除"
        danger
        onCancel={() => dialog.pop()}
        onConfirm={() => {
          void (async () => {
            const result = await sendCommand(`/remove-mcp ${id}`);
            onMessage(String(result?.message || `已删除 ${id}`));
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
      category: "MCP",
      value: `item:${it.id}`,
    })),
    {
      id: "__add__",
      title: "+ 添加 MCP",
      description: "/addmcp <name> <command> …",
      category: "操作",
      value: "__add__",
    },
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
          {" MCP"}
        </text>
        <DialogLoading />
      </box>
    );
  }

  return (
    <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
      {phase === "error" && error ? <DialogError text={error} /> : null}
      {phase === "ready" && items.length === 0 ? (
        <DialogError text="暂无 MCP — 可用「+ 添加」" />
      ) : null}
      <DialogSelect
        title="MCP 服务"
        options={options}
        categoryOrder={["MCP", "操作"]}
        onClose={onClose}
        onSelect={(opt) => {
          if (opt.value === "__add__") openAdd();
          else if (opt.value === "__refresh__") void reload();
          else if (opt.value.startsWith("item:")) confirmDelete(opt.value.slice(5), opt.title);
        }}
      />
    </box>
  );
}
