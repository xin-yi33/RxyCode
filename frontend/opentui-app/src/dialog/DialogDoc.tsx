/**
 * Scrollable help / tutorial / examples document dialog.
 */

import { useEffect, useState } from "react";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import { sendCommand } from "./api.ts";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { C } from "../theme.ts";

const STATIC_DOCS: Record<string, { title: string; body: string }> = {
  tutorial: {
    title: "交互式教程",
    body: [
      "1. Ctrl+P 打开命令面板，输入关键词过滤命令。",
      "2. Tab 在 Plan / Build / Compose 间切换。",
      "3. Ctrl+T 展开或折叠思考过程。",
      "4. /session /model /settings 均为独立窗口，Esc 关闭。",
      "5. 记忆、Skills、MCP 可在面板中管理，无需把长列表刷进聊天。",
    ].join("\n"),
  },
  quickstart: {
    title: "快速入门",
    body: [
      "• 直接输入需求开始对话（Build 模式会执行工具）。",
      "• Plan 模式只规划不落盘改代码。",
      "• Compose 模式适合多步编排。",
      "• /addmodel 用向导添加模型；/permission 调整审批档位。",
    ].join("\n"),
  },
  examples: {
    title: "使用示例",
    body: [
      "「帮我看看这个报错」→ Build",
      "「先列一个重构计划」→ Plan",
      "「打开会话列表」→ Ctrl+P → session",
      "「添加一条记忆」→ Ctrl+P → memory → + 添加",
    ].join("\n"),
  },
};

export function DialogDoc({
  kind,
  onClose,
}: {
  kind: "help" | "tutorial" | "quickstart" | "examples";
  onClose: () => void;
}) {
  const { height: termRows } = useTerminalDimensions();
  const maxLines = Math.max(6, Math.min(16, Math.floor((termRows || 24) / 2) - 4));
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [title, setTitle] = useState("帮助");
  const [lines, setLines] = useState<string[]>([]);
  const [scroll, setScroll] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      if (kind !== "help") {
        const doc = STATIC_DOCS[kind];
        setTitle(doc?.title || kind);
        setLines((doc?.body || "").split("\n"));
        setPhase("ready");
        return;
      }
      setPhase("loading");
      const result = await sendCommand("/help");
      const msg = String(result?.message || "");
      if (!msg && !result) {
        setError("无法加载帮助");
        setTitle("帮助");
        setLines(STATIC_DOCS.quickstart.body.split("\n"));
        setPhase("error");
        return;
      }
      setTitle("帮助");
      setLines((msg || STATIC_DOCS.quickstart.body).split("\n"));
      setPhase("ready");
    })();
  }, [kind]);

  useKeyboard((key) => {
    if (key.name === "escape") {
      key.preventDefault?.();
      onClose();
      return;
    }
    if (key.name === "up" || (key.ctrl && key.name === "p")) {
      key.preventDefault?.();
      setScroll((s) => Math.max(0, s - 1));
      return;
    }
    if (key.name === "down" || (key.ctrl && key.name === "n")) {
      key.preventDefault?.();
      setScroll((s) => Math.min(Math.max(0, lines.length - maxLines), s + 1));
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      onClose();
    }
  });

  const slice = lines.slice(scroll, scroll + maxLines);

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: C.borderDim,
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
      {phase === "loading" ? <DialogLoading /> : null}
      {phase === "error" && error ? <DialogError text={error} /> : null}
      {slice.map((line, i) => (
        <box key={i} style={{ width: "100%", height: 1 }}>
          <text fg={C.subtext} selectable>
            {`  ${line}`}
          </text>
        </box>
      ))}
      <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
        <text fg={C.overlay2}> ↑↓滚动  ↵/esc关闭 </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>
          {lines.length ? `${Math.min(scroll + 1, lines.length)}-${Math.min(scroll + slice.length, lines.length)}/${lines.length}` : "0/0"}{" "}
        </text>
      </box>
    </box>
  );
}
