import { useEffect, useState } from "react";
import { useKeyboard } from "@opentui/react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { listFromCommandResult, sendCommand } from "./api.ts";
import { C } from "../theme.ts";

export function DialogSession({
  onClose,
  onLoaded,
}: {
  onClose: () => void;
  onLoaded: (payload: { name: string; messages?: unknown[]; message?: string }) => void;
}) {
  const [options, setOptions] = useState<DialogSelectOption<string>[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      const result = await sendCommand("/session");
      const items = listFromCommandResult(result, "session");
      if (!items.length) {
        setError(String(result?.message || "暂无会话"));
        setOptions([]);
        return;
      }
      setOptions(
        items.map((it) => ({
          id: it.id,
          title: it.title,
          description: it.description,
          category: "会话",
          value: it.id,
        })),
      );
    })();
  }, []);

  useKeyboard((key) => {
    if (key.name === "escape" && options !== null && options.length === 0) {
      key.preventDefault?.();
      onClose();
    }
  });

  if (options === null) {
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

  if (options.length === 0) {
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
        <text fg={C.overlay2}>{"  "}{error}</text>
        <text fg={C.overlay2}>{"  esc 关闭"}</text>
      </box>
    );
  }

  return (
    <DialogSelect
      title="切换会话"
      options={options}
      categoryOrder={["会话"]}
      placeholder="搜索会话"
      onClose={onClose}
      onSelect={(opt) => {
        void (async () => {
          const result = await sendCommand(`/load-chat ${opt.value}`);
          onLoaded({
            name: opt.value,
            messages: (result?.messages as unknown[]) || undefined,
            message: String(result?.message || `已加载会话: ${opt.value}`),
          });
          onClose();
        })();
      }}
    />
  );
}
