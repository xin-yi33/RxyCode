import { useEffect, useState } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { PERMISSION_ITEMS } from "../Modal.tsx";
import { cycleToolCardsDefault, toolCardsDefaultExpanded } from "../lib/toolCardDisplay.ts";
import { composerMarkdownEnabled, cycleComposerMarkdown } from "../lib/markdownDisplay.ts";

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
  const [options, setOptions] = useState<DialogSelectOption<string>[]>([]);
  const [screen, setScreen] = useState<"root" | "router-model">("root");
  const [modelOptions, setModelOptions] = useState<DialogSelectOption<string>[]>([]);

  useEffect(() => {
    void (async () => {
      const result = await sendCommand("/settings");
      const items = Array.isArray(result?.items) ? result.items : [];
      setOptions([
        {
          id: "tool_cards",
          title: "工具结果默认展开",
          description: toolCardsDefaultExpanded() ? "当前：展开（点击工具名可单独折叠）" : "当前：折叠（点击工具名可单独展开）",
          category: "设置",
          value: "tool_cards",
        },
        {
          id: "composer_markdown",
          title: "对话 Markdown 渲染",
          description: composerMarkdownEnabled()
            ? "当前：开启（消息按 Markdown 呈现，输入框保持一行编辑）"
            : "当前：关闭（普通纯文本对话）",
          category: "设置",
          value: "composer_markdown",
        },
        ...items.map((raw) => {
          const item = raw as {
            id?: string;
            label?: string;
            desc?: string;
            disabled?: boolean;
          };
          return {
            id: String(item.id || ""),
            title: String(item.label || item.id || ""),
            description: item.disabled ? `${item.desc || ""}（不可用）` : String(item.desc || ""),
            category: String(item.id || "").startsWith("agents_") ? "专家团" : "设置",
            value: String(item.id || ""),
          };
        }),
      ]);
    })();
  }, []);

  if (screen === "router-model") {
    return (
      <DialogSelect
        title="难度判断模型"
        options={modelOptions}
        categoryOrder={["模型"]}
        showSearch={false}
        onClose={onClose}
        onSelect={(opt) => {
          void (async () => {
            await sendCommand(`/agents router-model ${opt.value}`);
            onClose();
          })();
        }}
      />
    );
  }

  return (
    <DialogSelect
      title="设置"
      options={options}
      categoryOrder={["设置", "专家团"]}
      showSearch={false}
      onClose={onClose}
      onSelect={(opt) => {
        if (opt.value === "tool_cards") {
          cycleToolCardsDefault();
          onClose();
        } else if (opt.value === "composer_markdown") {
          cycleComposerMarkdown();
          onClose();
        } else if (opt.value === "permission") onOpenPermission();
        else if (opt.value === "language") onOpenLanguage();
        else if (opt.value === "agents_enabled") {
          void (async () => {
            const result = await sendCommand("/settings");
            const items = Array.isArray(result?.items) ? result.items : [];
            const current = items.find((it) => (it as { id?: string }).id === "agents_enabled") as
              | { value?: boolean }
              | undefined;
            await sendCommand(current?.value ? "/agents off" : "/agents on");
            onClose();
          })();
        } else if (opt.value === "agents_router_model") {
          void (async () => {
            const result = await sendCommand("/models");
            const names = Array.isArray(result?.models)
              ? result.models.map((m: unknown) =>
                  typeof m === "string" ? m : String((m as { name?: string }).name || ""),
                )
              : [];
            setModelOptions([
              { id: "none", title: "不使用", description: "只用启发式，不调用判难度模型", category: "模型", value: "none" },
              ...names.filter(Boolean).map((name: string) => ({
                id: name,
                title: name,
                description: "用于第 3 级难度判断",
                category: "模型",
                value: name,
              })),
            ]);
            setScreen("router-model");
          })();
        } else if (opt.value === "agents_multi_model") {
          onClose();
        } else onClose();
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
