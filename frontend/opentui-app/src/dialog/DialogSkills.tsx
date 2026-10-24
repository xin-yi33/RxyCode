/**
 * Skills manager — list / install / find / remove-with-confirm.
 */

import { useCallback, useEffect, useState } from "react";
import { useDialog } from "./DialogHost.tsx";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogConfirm } from "./DialogConfirm.tsx";
import { DialogPrompt } from "./DialogPrompt.tsx";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { C } from "../theme.ts";

export function DialogSkills({
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
    const result = await sendCommand("/list-skills");
    if (!result) {
      setError("无法加载 Skills");
      setItems([]);
      setPhase("error");
      return;
    }
    setItems(listFromCommandResult(result, "skill"));
    setPhase("ready");
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openInstall = (cmdPrefix: string, title: string, placeholder: string) => {
    dialog.push(
      <DialogPrompt
        title={title}
        placeholder={placeholder}
        onCancel={() => dialog.pop()}
        onSubmit={(text) => {
          void (async () => {
            if (!text) {
              dialog.pop();
              return;
            }
            const result = await sendCommand(`${cmdPrefix} ${text}`);
            onMessage(String(result?.message || "已提交"));
            dialog.pop();
          })();
        }}
      />,
    );
  };

  const confirmDelete = (id: string, title: string) => {
    dialog.push(
      <DialogConfirm
        title="卸载 Skill"
        message={`确定卸载 ${title}？`}
        confirmLabel="卸载"
        danger
        onCancel={() => dialog.pop()}
        onConfirm={() => {
          void (async () => {
            const result = await sendCommand(`/remove-skill ${id}`);
            onMessage(String(result?.message || `已卸载 ${id}`));
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
      category: "Skills",
      value: `item:${it.id}`,
    })),
    {
      id: "__add__",
      title: "+ 安装 Skill",
      description: "/addskill <name|url>",
      category: "操作",
      value: "__add__",
    },
    {
      id: "__find__",
      title: "查找并下载",
      description: "/find-skill <name>",
      category: "操作",
      value: "__find__",
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
          {" Skills"}
        </text>
        <DialogLoading />
      </box>
    );
  }

  return (
    <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
      {phase === "error" && error ? <DialogError text={error} /> : null}
      {phase === "ready" && items.length === 0 ? (
        <DialogError text="暂无 Skill — 可用「+ 安装」" />
      ) : null}
      <DialogSelect
        title="Skills"
        options={options}
        categoryOrder={["Skills", "操作"]}
        onClose={onClose}
        onSelect={(opt) => {
          if (opt.value === "__add__") openInstall("/addskill", "安装 Skill", "name 或 url…");
          else if (opt.value === "__find__") openInstall("/find-skill", "查找 Skill", "skill 名称…");
          else if (opt.value === "__refresh__") void reload();
          else if (opt.value.startsWith("item:")) confirmDelete(opt.value.slice(5), opt.title);
        }}
      />
    </box>
  );
}
