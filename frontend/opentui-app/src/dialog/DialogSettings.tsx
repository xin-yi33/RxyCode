import { useEffect, useState } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { PERMISSION_ITEMS } from "../Modal.tsx";

export function DialogPermission({
  onClose,
  onChanged,
}: {
  onClose: () => void;
  onChanged: (mode: string, message: string) => void;
}) {
  const [current, setCurrent] = useState("confirm_all");

  useEffect(() => {
    void (async () => {
      const result = await sendCommand("/permission");
      const mode = String(result?.permission_mode || result?.mode || "confirm_all");
      setCurrent(mode);
    })();
  }, []);

  const options: DialogSelectOption<string>[] = PERMISSION_ITEMS.map((p) => ({
    id: p.id,
    title: p.label,
    description: p.desc,
    category: "权限",
    value: p.id,
  }));

  return (
    <DialogSelect
      title="权限设置"
      options={options}
      categoryOrder={["权限"]}
      currentId={current}
      showSearch={false}
      onClose={onClose}
      onSelect={(opt) => {
        void (async () => {
          const result = await sendCommand(`/permission ${opt.value}`);
          onChanged(opt.value, String(result?.message || `权限模式: ${opt.value}`));
          onClose();
        })();
      }}
    />
  );
}

export function DialogLanguage({
  onClose,
  onChanged,
}: {
  onClose: () => void;
  onChanged: (lang: string, message: string) => void;
}) {
  const options: DialogSelectOption<string>[] = [
    { id: "zh", title: "中文", description: "zh", category: "语言", value: "zh" },
    { id: "en", title: "English", description: "en", category: "语言", value: "en" },
  ];
  return (
    <DialogSelect
      title="切换语言"
      options={options}
      categoryOrder={["语言"]}
      showSearch={false}
      onClose={onClose}
      onSelect={(opt) => {
        void (async () => {
          const result = await sendCommand(`/language ${opt.value}`);
          onChanged(opt.value, String(result?.message || `Language: ${opt.value}`));
          onClose();
        })();
      }}
    />
  );
}

export function DialogSettings({
  onClose,
  onOpenPermission,
  onOpenLanguage,
}: {
  onClose: () => void;
  onOpenPermission: () => void;
  onOpenLanguage: () => void;
}) {
  const options: DialogSelectOption<string>[] = [
    {
      id: "permission",
      title: "权限设置",
      description: "三档安全审批",
      category: "设置",
      value: "permission",
    },
    {
      id: "language",
      title: "界面语言",
      description: "中文 / English",
      category: "设置",
      value: "language",
    },
  ];
  return (
    <DialogSelect
      title="设置"
      options={options}
      categoryOrder={["设置"]}
      showSearch={false}
      onClose={onClose}
      onSelect={(opt) => {
        if (opt.value === "permission") onOpenPermission();
        else if (opt.value === "language") onOpenLanguage();
        else onClose();
      }}
    />
  );
}

type ListKind = "memory" | "skill" | "mcp" | "queue" | "schedule";

const LIST_META: Record<
  ListKind,
  { title: string; command: string; category: string }
> = {
  memory: { title: "记忆", command: "/memory list", category: "记忆" },
  skill: { title: "Skills", command: "/list-skills", category: "Skills" },
  mcp: { title: "MCP 服务", command: "/list-mcp", category: "MCP" },
  queue: { title: "任务队列", command: "/queue", category: "系统" },
  schedule: { title: "定时任务", command: "/schedule", category: "系统" },
};

export function DialogCommandList({
  kind,
  onClose,
  onMessage,
}: {
  kind: ListKind;
  onClose: () => void;
  onMessage: (text: string) => void;
}) {
  const meta = LIST_META[kind];
  const [options, setOptions] = useState<DialogSelectOption<string>[]>([]);

  useEffect(() => {
    void (async () => {
      const result = await sendCommand(meta.command);
      const items = listFromCommandResult(result, kind);
      if (!items.length) {
        setOptions([
          {
            id: "__empty__",
            title: "(空)",
            description: String(result?.message || "暂无条目"),
            category: meta.category,
            value: "__empty__",
          },
        ]);
        return;
      }
      setOptions(
        items.map((it) => ({
          id: it.id,
          title: it.title,
          description: it.description,
          category: meta.category,
          value: it.id,
        })),
      );
    })();
  }, [kind, meta.category, meta.command]);

  return (
    <DialogSelect
      title={meta.title}
      options={options}
      categoryOrder={[meta.category]}
      onClose={onClose}
      onSelect={(opt) => {
        if (opt.value === "__empty__") {
          onClose();
          return;
        }
        onMessage(`${meta.title}: ${opt.title}${opt.description ? ` — ${opt.description}` : ""}`);
        onClose();
      }}
    />
  );
}

export function DialogHelp({ onClose }: { onClose: () => void }) {
  const options: DialogSelectOption<string>[] = [
    { id: "1", title: "Ctrl+P", description: "命令面板", category: "快捷键", value: "1" },
    { id: "2", title: "Ctrl+T", description: "展开/折叠思考", category: "快捷键", value: "2" },
    { id: "3", title: "Tab", description: "切换 Plan/Build/Compose", category: "快捷键", value: "3" },
    { id: "4", title: "/session", description: "切换会话", category: "命令", value: "4" },
    { id: "5", title: "/model", description: "选择模型", category: "命令", value: "5" },
    { id: "6", title: "/addmodel", description: "添加模型向导", category: "命令", value: "6" },
    { id: "7", title: "/settings", description: "设置 / 权限", category: "命令", value: "7" },
  ];
  return (
    <DialogSelect
      title="帮助"
      options={options}
      categoryOrder={["快捷键", "命令"]}
      onClose={onClose}
      onSelect={() => onClose()}
    />
  );
}

/** @deprecated Prefer DialogStatus from DialogStatus.tsx — re-exported for compatibility. */
export { DialogStatus } from "./DialogStatus.tsx";
