/**
 * Scrollable help / tutorial / examples document dialog.
 *
 * Arrow keys used to no-op because (1) App unmounts the composer while a
 * dialog is open, so ConPTY has no focused input, and (2) useKeyboard closed
 * over the initial empty `lines` array. Focus sink + refs + ScrollBox fix both.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import type { InputRenderable, ScrollBoxRenderable } from "@opentui/core";
import { sendCommand } from "./api.ts";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { C } from "../theme.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "../scroll.ts";

const STATIC_DOCS: Record<string, { title: string; body: string }> = {
  tutorial: {
    title: "交互式教程",
    body: [
      "1. Ctrl+P 打开命令面板，输入关键词过滤命令。",
      "2. Tab 在 Plan / Build / Compose 间切换。Plan 只规划不落盘。",
      "3. Ctrl+T 展开或折叠思考过程。",
      "4. /session /model /settings 均为独立窗口，Esc 关闭。",
      "5. 默认单 Agent 写代码。专家团默认关：/agents on 或 /team <可拆任务>。",
      "6. /why-mode 看上次为什么是 solo 还是 team。",
      "7. 记忆、Skills、MCP 可在面板中管理，无需把长列表刷进聊天。",
    ].join("\n"),
  },
  quickstart: {
    title: "快速入门",
    body: [
      "• 直接输入需求开始对话（Build 模式会执行工具）。默认不会走专家团。",
      "• Plan 模式只规划不落盘改代码。",
      "• Compose 模式适合多步编排。",
      "• /addmodel 用向导添加模型；/permission 调整审批档位。",
      "• 要看专家团：/team 做前后端…… 或先 /agents on。约 3× token。",
      "• /help 有完整命令和「为什么 coding 看不到专家团」。",
    ].join("\n"),
  },
  examples: {
    title: "使用示例",
    body: [
      "「帮我看看这个报错」→ Build（单 Agent）",
      "「先列一个重构计划」→ Plan",
      "「打开会话列表」→ Ctrl+P → session",
      "「添加一条记忆」→ Ctrl+P → memory → + 添加",
      "「前后端一起做、可独立验收」→ /team <任务>",
      "「这次不要专家团」→ /solo <任务>",
    ].join("\n"),
  },
};

export type DialogDocKind = "help" | "tutorial" | "quickstart" | "examples";

/** Visible body rows so the dialog fits under header/status/input chrome. */
export function docViewportLines(kind: DialogDocKind, termRows: number): number {
  const rows = termRows > 0 ? termRows : 24;
  const budget = Math.max(6, rows - 10);
  return kind === "help" ? Math.min(22, budget) : Math.min(12, budget);
}

export function clampDocScroll(scroll: number, lineCount: number, viewport: number): number {
  const max = Math.max(0, lineCount - Math.max(1, viewport));
  if (!Number.isFinite(scroll)) return 0;
  return Math.min(max, Math.max(0, Math.trunc(scroll)));
}

function isUpKey(key: { name?: string; ctrl?: boolean }): boolean {
  return key.name === "up" || key.name === "arrowup" || Boolean(key.ctrl && key.name === "p");
}

function isDownKey(key: { name?: string; ctrl?: boolean }): boolean {
  return key.name === "down" || key.name === "arrowdown" || Boolean(key.ctrl && key.name === "n");
}

export function DialogDoc({
  kind,
  onClose,
  body,
}: {
  kind: DialogDocKind;
  onClose: () => void;
  /** Skip /help fetch — used by tests and fallbacks. */
  body?: string;
}) {
  const { height: termRows } = useTerminalDimensions();
  const viewport = docViewportLines(kind, termRows || 24);
  const scrollAccel = useMemo(() => createScrollAcceleration(), []);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">(
    kind === "help" && body == null ? "loading" : "ready",
  );
  const [title, setTitle] = useState(kind === "help" ? "帮助" : STATIC_DOCS[kind]?.title || kind);
  const [lines, setLines] = useState<string[]>(() => {
    if (body != null) return body.split("\n");
    if (kind !== "help") return (STATIC_DOCS[kind]?.body || "").split("\n");
    return [];
  });
  const [scroll, setScroll] = useState(0);
  const [error, setError] = useState("");
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const focusRef = useRef<InputRenderable>(null);
  const linesRef = useRef(lines);
  const viewportRef = useRef(viewport);
  const offsetRef = useRef(0);
  linesRef.current = lines;
  viewportRef.current = viewport;

  useEffect(() => {
    try {
      focusRef.current?.focus();
    } catch {
      // ignore
    }
  }, [phase]);

  useEffect(() => {
    void (async () => {
      if (body != null) {
        setTitle(kind === "help" ? "帮助" : STATIC_DOCS[kind]?.title || kind);
        setLines(body.split("\n"));
        setPhase("ready");
        return;
      }
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
  }, [kind, body]);

  const applyScroll = (next: number) => {
    const clamped = clampDocScroll(next, linesRef.current.length, viewportRef.current);
    offsetRef.current = clamped;
    setScroll(clamped);
    try {
      const box = scrollRef.current;
      if (box) box.scrollTop = clamped;
    } catch {
      // ignore
    }
  };

  useKeyboard((key) => {
    if (key.name === "escape" || key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      onClose();
      return;
    }
    const page = Math.max(1, viewportRef.current - 1);
    if (key.name === "pageup" || key.name === "home") {
      key.preventDefault?.();
      applyScroll(key.name === "home" ? 0 : offsetRef.current - page);
      return;
    }
    if (key.name === "pagedown" || key.name === "end") {
      key.preventDefault?.();
      applyScroll(
        key.name === "end" ? linesRef.current.length : offsetRef.current + page,
      );
      return;
    }
    if (isUpKey(key)) {
      key.preventDefault?.();
      applyScroll(offsetRef.current - 1);
      return;
    }
    if (isDownKey(key)) {
      key.preventDefault?.();
      applyScroll(offsetRef.current + 1);
    }
  });

  const safeScroll = clampDocScroll(scroll, lines.length, viewport);
  const sliceStart = safeScroll + 1;
  const sliceEnd = Math.min(safeScroll + viewport, lines.length);

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
      <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
        <text fg={C.text} attributes={1}>
          {" "}
          {title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </box>
      {phase === "loading" ? <DialogLoading /> : null}
      {phase === "error" && error ? <DialogError text={error} /> : null}
      <scrollbox
        ref={scrollRef}
        stickyScroll={false}
        stickyStart="top"
        scrollAcceleration={scrollAccel}
        style={{
          rootOptions: {
            flexShrink: 0,
            height: viewport,
            maxHeight: viewport,
            border: false,
            backgroundColor: C.bg,
          },
          viewportOptions: { flexGrow: 1, backgroundColor: C.bg },
          contentOptions: { backgroundColor: C.bg },
          verticalScrollbarOptions: {
            showArrows: false,
            trackOptions: {
              foregroundColor: SCROLLBAR_TRACK.foregroundColor,
              backgroundColor: SCROLLBAR_TRACK.backgroundColor,
            },
          },
        }}
      >
        {lines.map((line, i) => (
          <box key={i} style={{ width: "100%", height: 1, flexShrink: 0 }}>
            <text fg={C.subtext} selectable>
              {`  ${line}`}
            </text>
          </box>
        ))}
      </scrollbox>
      <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
        <text fg={C.overlay2}> ↑↓滚动  PgUp/PgDn  ↵/esc关闭 </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>
          {lines.length ? `${sliceStart}-${sliceEnd}/${lines.length}` : "0/0"}{" "}
        </text>
      </box>
      <input
        ref={focusRef}
        focused
        value=""
        onInput={() => undefined}
        style={{
          position: "absolute",
          left: -10000,
          top: 0,
          opacity: 0,
          flexShrink: 0,
        }}
      />
    </box>
  );
}
