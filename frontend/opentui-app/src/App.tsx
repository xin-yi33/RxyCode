import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ScrollBoxRenderable, TextareaRenderable, Selection } from "@opentui/core";
import { decodePasteBytes, stripAnsiSequences } from "@opentui/core";
import {
  useKeyboard,
  usePaste,
  useRenderer,
  useSelectionHandler,
  useTerminalDimensions,
} from "@opentui/react";
import { cancelActiveRequest, fetchStatus, respondApproval, sendChatMessage, sendCommand } from "./chatApi.ts";
import { ApprovalDialog, type ApprovalInfo } from "./ApprovalDialog.tsx";
import { classifyInput, formatCommandResult } from "./commandRouter.ts";
import { filterCommands, AVAILABLE_COMMANDS, type Command } from "./commands.ts";
import { formatHeaderLine, formatInputHint, formatMessageLine, messageFg } from "./format.ts";
import { buildStatusSegments, formatStatusBarText } from "./statusBar.ts";
import {
  createStickyState,
  onSendMessage,
  onScrollToBottom,
  onUserScrollUp,
  shouldAutoStick,
  type StickyState,
} from "./sticky.ts";
import { C } from "./theme.ts";
import {
  MODE_COLORS,
  MODE_LABELS,
  MODES,
  type ChatMessage,
  type Mode,
  type StatusInfo,
} from "./types.ts";
import {
  WELCOME_ROWS,
  SHORTCUTS_HINT,
  WORDMARK,
  BRAND_LIGHT,
  BRAND_HOT,
  BRAND_MUTED,
  LOGO_FIELD_BG,
  logoInkForRow,
} from "./brand.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "./scroll.ts";
import { MarkdownView } from "./Markdown.tsx";
import {
  inputVisibleLines,
  needsInputScroll,
  numInputLines,
  wrapContentLines,
} from "./layout.ts";
import { DialogOutlet } from "./dialog/DialogHost.tsx";
import { useSettingsDialogs } from "./dialog/useSettingsDialogs.tsx";

function cycleMode(mode: Mode): Mode {
  const idx = MODES.indexOf(mode);
  return MODES[(idx + 1) % MODES.length];
}

const SUBTITLE_CORE = "General-Purpose AI Agent";
const USER_FRAME_LINE = "\u2500".repeat(40);
const USER_FRAME_BAR = "\u2588";
const SPINNER_FRAMES = [
  "\u280B",
  "\u2819",
  "\u2839",
  "\u2838",
  "\u283C",
  "\u2834",
  "\u2826",
  "\u2827",
  "\u2807",
  "\u280F",
];
const MAX_STREAMING_THINKING_LINES = 8;
const MAX_EXPANDED_DONE_THINKING_LINES = 40;

/**
 * Classic Ink Banner wordmark: Unicode █ rows.
 * Only FULL BLOCK cells get fg+bg fill (spaces stay transparent) — matches Ink WordmarkRow.
 */
function WordmarkRow({ line, ink, leading }: { line: string; ink: string; leading: number }) {
  const nodes: Array<{ text: string; solid: boolean }> = [];
  let buf = "";
  let solid: boolean | null = null;
  for (const ch of line.replace(/ +$/, "")) {
    const isSolid = ch === "█";
    if (solid === null) {
      solid = isSolid;
      buf = ch;
      continue;
    }
    if (isSolid === solid) {
      buf += ch;
      continue;
    }
    nodes.push({ text: buf, solid });
    buf = ch;
    solid = isSolid;
  }
  if (buf && solid !== null) nodes.push({ text: buf, solid });

  return (
    <text bg={LOGO_FIELD_BG}>
      <span>{" ".repeat(Math.max(0, leading))}</span>
      {nodes.map((seg, j) =>
        seg.solid ? (
          <span key={j} fg={ink} bg={ink} attributes={1}>
            {seg.text}
          </span>
        ) : (
          <span key={j}>{seg.text}</span>
        ),
      )}
    </text>
  );
}

function BrandLogo({ cols }: { cols: number }) {
  const displayWidth = WORDMARK[0].replace(/ +$/, "").length;
  const leading = Math.max(0, Math.floor((cols - displayWidth) / 2));
  return (
    <box style={{ flexDirection: "column", width: "100%", backgroundColor: LOGO_FIELD_BG }}>
      {WORDMARK.map((line, i) => (
        <WordmarkRow key={`wm-${i}`} line={line} ink={logoInkForRow(i)} leading={leading} />
      ))}
    </box>
  );
}

function WelcomeBanner({ cols }: { cols: number }) {
  const subtitlePad = Math.max(0, Math.floor((cols - (SUBTITLE_CORE.length + 4)) / 2));
  return (
    <box style={{ flexDirection: "column", paddingTop: 1, paddingBottom: 1, width: "100%", backgroundColor: C.bg }}>
      <BrandLogo cols={cols} />
      <box style={{ height: 1, backgroundColor: C.bg }} />
      <box style={{ flexDirection: "row", width: "100%", height: 1, backgroundColor: C.bg }}>
        <text bg={C.bg}>{" ".repeat(subtitlePad)}</text>
        <text fg={BRAND_LIGHT} bg={C.bg}>
          {"✦ "}
        </text>
        <text fg={BRAND_HOT} bg={C.bg}>
          {SUBTITLE_CORE}
        </text>
        <text fg={BRAND_LIGHT} bg={C.bg}>
          {" ✦"}
        </text>
      </box>
      <box style={{ height: 1, backgroundColor: C.bg }} />
      {WELCOME_ROWS.map((row, i) => (
        <text key={`w-${i}`} bg={C.bg} selectable>
          {row.parts.map((part, j) => (
            <span key={j} fg={part.fg} attributes={part.bold ? 1 : 0}>
              {part.text}
            </span>
          ))}
        </text>
      ))}
    </box>
  );
}

function ThinkingSpinner({ done }: { done?: boolean }) {
  const [spinnerIdx, setSpinnerIdx] = useState(0);
  useEffect(() => {
    if (done) return;
    const iv = setInterval(() => setSpinnerIdx((prev) => (prev + 1) % SPINNER_FRAMES.length), 80);
    return () => clearInterval(iv);
  }, [done]);
  return (
    <span fg={C.yellow} attributes={1}>
      {"  "}
      {done ? "\u2713" : SPINNER_FRAMES[spinnerIdx]}
    </span>
  );
}

/** Ink-parity Thought header + gated gray self-talk body. */
function ThoughtMessage({
  content,
  done,
  expanded,
}: {
  content: string;
  done?: boolean;
  expanded: boolean;
}) {
  const displayContent = content || "思考中...";
  const allLines = displayContent.split("\n").filter((l) => l.trim());
  let lines: string[] = [];
  let clipped = 0;
  // User rule: self-talk body only when thinking mode is ON.
  if (expanded) {
    if (done) {
      lines =
        allLines.length <= MAX_EXPANDED_DONE_THINKING_LINES
          ? allLines
          : allLines.slice(-MAX_EXPANDED_DONE_THINKING_LINES);
      clipped = allLines.length - lines.length;
    } else {
      lines = allLines.slice(-MAX_STREAMING_THINKING_LINES);
      clipped = allLines.length - lines.length;
    }
  }
  return (
    <box style={{ flexDirection: "column", width: "100%", paddingLeft: 1, backgroundColor: C.bg }}>
      <text selectable>
        <ThinkingSpinner done={done} />
        <span fg={C.yellow} attributes={1}>
          {" "}
          Thought
        </span>
        <span fg={C.overlay2}>
          {" "}
          (/thinking {expanded ? "collapse" : "expand"})
        </span>
      </text>
      {expanded
        ? lines.map((line, i) => (
            <text key={i} fg={BRAND_MUTED} selectable>
              {"    "}
              {line}
            </text>
          ))
        : null}
      {expanded && clipped > 0 ? (
        <text fg={C.overlay2} selectable>
          {"    "}… (+{clipped} 行)
        </text>
      ) : null}
    </box>
  );
}

/** Ink-parity user bubble: left █ on every content line + top/bottom ─ rules. */
function UserMessage({
  content,
  modeColor,
  wrapW,
}: {
  content: string;
  modeColor: string;
  wrapW: number;
}) {
  const lines = wrapContentLines(content, Math.max(8, wrapW));
  return (
    <box style={{ flexDirection: "column", width: "100%", paddingLeft: 1, paddingTop: 0, backgroundColor: C.bg }}>
      <text selectable>
        <span fg={modeColor}>{"  "}{USER_FRAME_BAR}</span>
        <span fg={C.borderDim}>{USER_FRAME_LINE}</span>
      </text>
      {lines.map((line, i) => (
        <text key={i} selectable>
          <span fg={modeColor}>{"  "}{USER_FRAME_BAR}</span>
          <span fg={C.text}>{" "}{line}</span>
        </text>
      ))}
      <text selectable>
        <span fg={modeColor}>{"  "}{USER_FRAME_BAR}</span>
        <span fg={C.borderDim}>{USER_FRAME_LINE}</span>
      </text>
    </box>
  );
}

function ChatLine({
  msg,
  thinkingExpanded,
  modeColor,
  wrapW,
}: {
  msg: ChatMessage;
  thinkingExpanded: boolean;
  modeColor: string;
  wrapW: number;
}) {
  if (msg.role === "thinking") {
    return <ThoughtMessage content={msg.content} done={msg.done} expanded={thinkingExpanded} />;
  }
  if (msg.role === "user") {
    const frameColor =
      msg.mode && MODE_COLORS[msg.mode] ? MODE_COLORS[msg.mode] : modeColor;
    return <UserMessage content={msg.content} modeColor={frameColor} wrapW={wrapW} />;
  }
  if (msg.role === "assistant") {
    // Stream as plain text; render Markdown only when settled (stable, less CPU).
    if (msg.done) {
      return (
        <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
          <MarkdownView content={msg.content} />
        </box>
      );
    }
    return (
      <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
        <text fg={messageFg("assistant")} selectable>
          {msg.content}
        </text>
      </box>
    );
  }
  if (msg.role === "tool") {
    const st = msg.toolStatus || "running";
    const icon = st === "running" ? "…" : st === "success" ? "✓" : "✗";
    return (
      <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1, flexDirection: "column" }}>
        <text selectable>
          <span fg={st === "error" ? C.yellow : C.subtext}>
            {`  ${icon} ${msg.toolName || "tool"} [${st}]`}
          </span>
        </text>
        {msg.content ? (
          <text fg={C.overlay2} selectable>
            {"    "}
            {msg.content.split("\n").slice(0, 5).join("\n")}
          </text>
        ) : null}
      </box>
    );
  }
  return (
    <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
      <text fg={messageFg(msg.role)} selectable>
        {formatMessageLine(msg)}
      </text>
    </box>
  );
}

export default function App() {
  const { width } = useTerminalDimensions();
  const cols = width || 80;
  const renderer = useRenderer();
  const [mode, setMode] = useState<Mode>("build");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<ApprovalInfo | null>(null);
  const [progress, setProgress] = useState("");
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [sticky, setSticky] = useState<StickyState>(createStickyState());
  const [inputValue, setInputValue] = useState("");
  const [paletteIdx, setPaletteIdx] = useState(0);
  const [permissionMode, setPermissionMode] = useState("confirm_all");
  const textareaRef = useRef<TextareaRenderable>(null);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingTogglePendingRef = useRef(false);
  const selectionRef = useRef<Selection | null>(null);
  /** OpenCode-style: first Ctrl+C arms quit; second within window exits. */
  const quitArmedUntilRef = useRef(0);
  const stickyRef = useRef(sticky);
  stickyRef.current = sticky;

  const scrollAccel = useMemo(() => createScrollAcceleration(), []);

  const model = status?.model || process.env.RXYCODE_MODEL || "unknown";
  const thinkingLive = isStreaming && thinkingExpanded;
  const modeColor = MODE_COLORS[mode] || C.brandHot;
  const modeLabel = MODE_LABELS[mode];

  useEffect(() => {
    void fetchStatus(setStatus);
    const iv = setInterval(() => void fetchStatus(setStatus), 30000);
    return () => clearInterval(iv);
  }, []);

  // Only re-focus input when streaming ends — never every mode tick (selection-safe).
  const wasStreamingRef = useRef(false);
  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      try {
        textareaRef.current?.focus();
      } catch {
        // ignore
      }
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

  const reengageSticky = useCallback(() => {
    const next = onSendMessage(stickyRef.current);
    setSticky(next);
    try {
      const box = scrollRef.current;
      if (box) box.scrollTop = Math.max(0, box.scrollHeight);
    } catch {
      // ignore
    }
  }, []);

  const copySelection = useCallback(() => {
    const sel = selectionRef.current;
    const text = sel?.getSelectedText?.()?.trim() ?? "";
    if (!text) return false;
    try {
      renderer.copyToClipboardOSC52(text);
      return true;
    } catch {
      return false;
    }
  }, [renderer]);

  useSelectionHandler((sel: Selection) => {
    selectionRef.current = sel;
    // Auto-copy when mouse selection ends (OpenCode-like).
    if (sel && !sel.isDragging && sel.isActive) {
      const text = sel.getSelectedText?.() ?? "";
      if (text.trim()) {
        try {
          renderer.copyToClipboardOSC52(text);
        } catch {
          // ignore
        }
      }
    }
  });

  const toggleThinking = useCallback(async () => {
    if (thinkingTogglePendingRef.current) return;
    thinkingTogglePendingRef.current = true;
    try {
      const result = await sendCommand("/thinking");
      if (result && typeof result.expanded === "boolean") {
        setThinkingExpanded(result.expanded);
      } else {
        setThinkingExpanded((v) => !v);
      }
    } finally {
      thinkingTogglePendingRef.current = false;
    }
  }, []);

  const pushSystem = useCallback((content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-sys-${Math.random().toString(36).slice(2, 6)}`,
        role: "system",
        content,
        timestamp: Date.now(),
      },
    ]);
  }, []);

  const clearInput = useCallback(() => {
    setInputValue("");
    textareaRef.current?.setText("");
    setPaletteIdx(0);
  }, []);

  const statusLine = status
    ? `${status.model || "?"} · ${status.mode || mode} · ctx ${status.context_used_k ?? 0}k`
    : "offline";

  const settingsDialogs = useSettingsDialogs({
    pushSystem,
    setMessages,
    fetchStatus: () => void fetchStatus(setStatus),
    clearInput,
    statusLine,
    activeModel: model,
    setPermissionMode,
    onFallbackCommand: (cmd) => {
      void submitTextRef.current?.(cmd.name);
    },
  });

  const submitTextRef = useRef<((text: string) => Promise<void>) | null>(null);

  const { dialogOpen, openPalette, openPermission, openSession, openModel, openAddModel, routePaletteCommand } =
    settingsDialogs;

  usePaste((event) => {
    // Nested dialogs own paste (focused search input). Do not preventDefault.
    if (isStreaming || dialogOpen || pendingApproval) return;
    let text = "";
    try {
      text = stripAnsiSequences(decodePasteBytes(event.bytes));
    } catch {
      try {
        text = new TextDecoder().decode(event.bytes);
      } catch {
        return;
      }
    }
    if (!text) return;
    try {
      event.preventDefault();
    } catch {
      // ignore
    }
    const ta = textareaRef.current;
    if (!ta) return;
    try {
      ta.focus();
      ta.insertText(text);
      setInputValue(ta.plainText ?? "");
    } catch {
      // ignore
    }
  });

  useEffect(() => {
    try {
      if (dialogOpen || pendingApproval) {
        textareaRef.current?.blur?.();
      } else if (!isStreaming) {
        textareaRef.current?.focus?.();
      }
    } catch {
      // ignore
    }
  }, [dialogOpen, pendingApproval, isStreaming]);

  useEffect(() => {
    if (process.env.RXYCODE_OPEN_PALETTE === "1") {
      openPalette();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runLocalOrRemoteCommand = useCallback(
    async (name: string, args: string, raw: string, local: boolean) => {
      if (local) {
        if (name === "/clear") {
          setMessages([]);
          setProgress("");
          reengageSticky();
          clearInput();
          return;
        }
        if (name === "/build" || name === "/plan" || name === "/compose") {
          setMode(name.slice(1) as Mode);
          clearInput();
          return;
        }
        if (name === "/thinking") {
          await toggleThinking();
          clearInput();
          return;
        }
      }

      // Prefer the same dialog router as Ctrl+P (single source of truth).
      const catalog = AVAILABLE_COMMANDS.find((c) => c.name === name);
      if (catalog) {
        const dialogish =
          catalog.action ||
          [
            "/help",
            "/tutorial",
            "/quickstart",
            "/examples",
            "/cache",
            "/language",
            "/memory add",
            "/memory remove",
            "/memory search",
            "/addskill",
            "/find-skill",
            "/remove-skill",
            "/addmcp",
            "/remove-mcp",
            "/settings",
            "/permission",
            "/session",
            "/model",
            "/models",
            "/addmodel",
            "/list-skills",
            "/list-mcp",
            "/queue",
            "/schedule",
            "/memory list",
          ].includes(name);
        if (dialogish && !args) {
          routePaletteCommand(catalog);
          return;
        }
        // Bare family names without args also open managers
        if (!args && (name === "/memory add" || name.startsWith("/memory"))) {
          routePaletteCommand(catalog);
          return;
        }
      }

      if (name === "/permission" && !args) {
        openPermission();
        clearInput();
        return;
      }
      if (name === "/session" || name === "/list-chats") {
        openSession();
        clearInput();
        return;
      }
      if ((name === "/model" || name === "/models") && !args) {
        openModel();
        clearInput();
        return;
      }
      if (name === "/addmodel" && !args) {
        openAddModel();
        clearInput();
        return;
      }

      const cmd = args ? `${name} ${args}` : name;
      const toSend = cmd === "/model" ? "/models" : cmd;
      const result = await sendCommand(toSend);
      if (name === "/thinking" && result && typeof result.expanded === "boolean") {
        setThinkingExpanded(result.expanded);
      }
      if (name === "/permission" && result && typeof result.permission_mode === "string") {
        setPermissionMode(result.permission_mode);
      }
      pushSystem(formatCommandResult(result, raw));
      void fetchStatus(setStatus);
      clearInput();
    },
    [
      clearInput,
      openAddModel,
      openModel,
      openPermission,
      openSession,
      pushSystem,
      reengageSticky,
      routePaletteCommand,
      toggleThinking,
    ],
  );

  const onApprovalRequest = useCallback((info: ApprovalInfo | null) => {
    setPendingApproval((prev) => {
      if (info === null) return null;
      if (prev && prev.approvalId === info.approvalId) return prev;
      return info;
    });
    if (info) setProgress(`等待确认: ${info.tool}`);
  }, []);

  const onApprovalDecision = useCallback(
    async (decision: "approved" | "rejected" | "always_allow_level") => {
      const pending = pendingApproval;
      if (!pending) return;
      setPendingApproval(null);
      const ok = await respondApproval(pending.approvalId, decision);
      if (!ok) {
        pushSystem(`Approval failed for ${pending.tool}`);
      }
    },
    [pendingApproval, pushSystem],
  );

  const submitText = useCallback(
    async (raw: string) => {
      const classified = classifyInput(raw);
      if (classified.kind === "chat" && !classified.text) return;
      if (isStreaming) return;

      if (classified.kind === "command") {
        await runLocalOrRemoteCommand(
          classified.name,
          classified.args,
          classified.raw,
          classified.local,
        );
        return;
      }

      const trimmed = classified.text;
      reengageSticky();
      clearInput();

      const controller = new AbortController();
      abortRef.current = controller;
      await sendChatMessage(
        trimmed,
        mode,
        {
          onMessages: setMessages,
          onStreaming: setIsStreaming,
          onStatus: setStatus,
          onProgress: setProgress,
          onApprovalRequest,
        },
        controller.signal,
      );
      setPendingApproval(null);
      abortRef.current = null;
      textareaRef.current?.focus();
    },
    [clearInput, isStreaming, mode, onApprovalRequest, reengageSticky, runLocalOrRemoteCommand],
  );

  submitTextRef.current = submitText;

  const slashSuggestions = useMemo(() => {
    if (dialogOpen) return [] as Command[];
    if (inputValue.trimStart().startsWith("/")) return filterCommands(inputValue.trim(), 8);
    return [] as Command[];
  }, [inputValue, dialogOpen]);

  const inputWrapW = Math.max(20, cols - 6);
  const inputHeight = inputVisibleLines(inputValue, inputWrapW);
  const inputScroll = needsInputScroll(inputValue, inputWrapW);

  useKeyboard((key) => {
    if (pendingApproval || dialogOpen) {
      // Nested dialogs / approval own keyboard; Ctrl+P only opens when closed.
      if (dialogOpen && !(key.ctrl && key.name === "p")) return;
      if (pendingApproval && !(key.ctrl && key.name === "p")) return;
    }
    if (key.ctrl && key.name === "p") {
      if (!dialogOpen) {
        key.preventDefault();
        openPalette();
      }
      return;
    }

    if (dialogOpen) {
      return;
    }

    if (key.name === "tab" && !key.shift) {
      key.preventDefault();
      if (inputValue.trimStart().startsWith("/") && slashSuggestions.length > 0) {
        const cmd = slashSuggestions[Math.min(paletteIdx, slashSuggestions.length - 1)];
        if (cmd) {
          setInputValue(cmd.name + " ");
          textareaRef.current?.setText(cmd.name + " ");
        }
        return;
      }
      setMode((m) => cycleMode(m));
      void fetchStatus(setStatus);
      return;
    }
    if (key.ctrl && (key.name === "c" || key.name === "C")) {
      // OpenCode parity: copy → cancel → clear input → double Ctrl+C to quit.
      // Never exit on a single Ctrl+C (Windows users press it to copy).
      key.preventDefault();
      if (copySelection()) {
        quitArmedUntilRef.current = 0;
        return;
      }
      if (isStreaming && abortRef.current) {
        void cancelActiveRequest();
        abortRef.current.abort();
        abortRef.current = null;
        quitArmedUntilRef.current = 0;
        return;
      }
      const draft = (textareaRef.current?.plainText ?? inputValue).trim();
      if (draft) {
        clearInput();
        textareaRef.current?.focus();
        quitArmedUntilRef.current = 0;
        return;
      }
      const now = Date.now();
      if (now < quitArmedUntilRef.current) {
        quitArmedUntilRef.current = 0;
        try {
          process.emit("SIGINT");
        } catch {
          process.exit(0);
        }
        return;
      }
      quitArmedUntilRef.current = now + 2000;
      pushSystem("再按一次 Ctrl+C 退出 RxyCode（2 秒内）");
      return;
    }
    if (key.ctrl && key.name === "t") {
      key.preventDefault();
      void toggleThinking();
      return;
    }
    if (key.name === "return" && !key.shift && !key.meta && !key.ctrl) {
      const text = textareaRef.current?.plainText ?? inputValue;
      if (text.trim() && !isStreaming && !text.includes("\n")) {
        key.preventDefault();
        void submitText(text);
      }
      return;
    }
    if (key.name === "escape") {
      if (isStreaming && abortRef.current) {
        void cancelActiveRequest();
        abortRef.current.abort();
        abortRef.current = null;
        setInputValue("");
        textareaRef.current?.setText("");
        textareaRef.current?.focus();
      }
      return;
    }
    if (key.name === "pageup" || (key.name === "up" && key.ctrl)) {
      setSticky(onUserScrollUp(stickyRef.current));
      return;
    }
    if (key.name === "pagedown" || (key.name === "down" && key.ctrl)) {
      setSticky(onScrollToBottom(stickyRef.current));
      try {
        const box = scrollRef.current;
        if (box) box.scrollTop = Math.max(0, box.scrollHeight);
      } catch {
        // ignore
      }
    }
  });

  // Always keep thinking rows so Thought header + spinner stay visible.
  const visibleMessages = messages;

  const stickyEnabled = shouldAutoStick(sticky);
  void formatHeaderLine(mode, model, thinkingLive);

  const statusSegments = buildStatusSegments({
    connected: status !== null,
    contextUsedK: status?.context_used_k ?? 0,
    contextMaxK: status?.context_max_k ?? 256,
    cacheSize: status?.cache_size ?? "0B",
    cacheRate: status?.cache_rate ?? "0.0%",
    mode,
    thinkingExpanded,
    width: cols,
    modeColor,
  });
  void formatStatusBarText;

  return (
    <box
      style={{
        flexDirection: "column",
        width: "100%",
        height: "100%",
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexShrink: 0, paddingLeft: 1, paddingRight: 1, height: 1 }}>
        <text selectable>
          <span fg={BRAND_LIGHT} attributes={1}>
            {"  "}RxyCode v1.2.0
          </span>
          <span fg={BRAND_MUTED}>{" · "}</span>
          <span fg={modeColor} attributes={1}>
            {modeLabel}
          </span>
          <span fg={BRAND_MUTED}>{" · "}</span>
          <span fg={BRAND_HOT}>{model}</span>
          {thinkingLive ? <span fg={C.thinking}>{" · 思考中"}</span> : null}
        </text>
      </box>

      <scrollbox
        ref={scrollRef}
        stickyScroll={stickyEnabled}
        stickyStart="bottom"
        flexGrow={1}
        scrollAcceleration={scrollAccel}
        style={{
          rootOptions: { flexGrow: 1, border: false, backgroundColor: C.bg },
          viewportOptions: { flexGrow: 1, backgroundColor: C.bg, paddingRight: 1 },
          contentOptions: { flexGrow: 1, backgroundColor: C.bg },
          verticalScrollbarOptions: {
            showArrows: false,
            paddingLeft: 1,
            trackOptions: {
              foregroundColor: SCROLLBAR_TRACK.foregroundColor,
              backgroundColor: SCROLLBAR_TRACK.backgroundColor,
            },
          },
        }}
      >
        {visibleMessages.length === 0 ? (
          <WelcomeBanner cols={cols} />
        ) : (
          visibleMessages.map((msg) => (
            <ChatLine
              key={msg.id}
              msg={msg}
              thinkingExpanded={thinkingExpanded}
              modeColor={modeColor}
              wrapW={Math.max(20, cols - 8)}
            />
          ))
        )}
      </scrollbox>

      {progress ? (
        <box style={{ flexShrink: 0, paddingLeft: 1, height: 1 }}>
          <text fg={C.yellow}>{progress}</text>
        </box>
      ) : null}

      <DialogOutlet />

      {!dialogOpen && slashSuggestions.length > 0 ? (
        <box
          style={{
            flexShrink: 0,
            flexDirection: "column",
            paddingLeft: 1,
            paddingRight: 1,
            backgroundColor: C.surface0,
            maxHeight: 10,
          }}
        >
          <text fg={C.yellow} attributes={1}>
            {"  命令建议 (Tab 补全)"}
          </text>
          {slashSuggestions.map((cmd, i) => (
            <box
              key={cmd.name}
              style={{ width: "100%" }}
              onMouseDown={() => {
                setInputValue(cmd.name + " ");
                textareaRef.current?.setText(cmd.name + " ");
              }}
            >
              <text fg={i === paletteIdx ? BRAND_HOT : C.subtext}>
                {i === paletteIdx ? " › " : "   "}
                {cmd.name}
                <span fg={C.overlay2}>{`  ${cmd.description}`}</span>
              </text>
            </box>
          ))}
        </box>
      ) : null}

      {/* Gray shortcuts ABOVE the input dialog */}
      <box style={{ flexShrink: 0, paddingLeft: 1, paddingRight: 1, height: 1, backgroundColor: C.bg }}>
        <text fg={BRAND_MUTED}>{SHORTCUTS_HINT}</text>
      </box>

      {pendingApproval ? (
        <ApprovalDialog approval={pendingApproval} onDecision={onApprovalDecision} />
      ) : dialogOpen ? null : (
      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor: modeColor,
          borderStyle: "rounded",
          paddingLeft: 1,
          paddingRight: 1,
          backgroundColor: C.bg,
          minHeight: 2 + inputHeight,
        }}
      >
        <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
          <box style={{ flexDirection: "row", width: "100%" }}>
            <text fg={modeColor} attributes={1}>
              {" "}
              {modeLabel}{" "}
            </text>
            <text fg={C.overlay2}>{"· "}</text>
            <text fg={C.mauve}>{formatInputHint(isStreaming)}</text>
            {isStreaming ? <text fg={C.yellow}>{" ESC 取消"}</text> : null}
            <box style={{ flexGrow: 1 }} />
            <text fg={C.overlay2}>{permissionMode} </text>
          </box>
          <box style={{ flexDirection: "row", width: "100%", height: inputHeight }}>
            <text fg={modeColor} attributes={1}>
              {"> "}
            </text>
            {inputScroll ? (
              <scrollbox
                style={{
                  rootOptions: {
                    flexGrow: 1,
                    height: inputHeight,
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
                <textarea
                  ref={textareaRef}
                  focused={!isStreaming && !dialogOpen}
                  placeholder={isStreaming ? "处理中..." : "输入指令或需求..."}
                  initialValue={inputValue}
                  onContentChange={() => {
                    const next = textareaRef.current?.plainText ?? "";
                    setInputValue(next);
                    if (next.trimStart().startsWith("/")) setPaletteIdx(0);
                  }}
                  onSubmit={() => {
                    const text = textareaRef.current?.plainText ?? inputValue;
                    void submitText(text);
                  }}
                  style={{ flexGrow: 1, height: Math.max(inputHeight, numInputLines(inputValue, inputWrapW)), backgroundColor: C.bg }}
                />
              </scrollbox>
            ) : (
              <textarea
                ref={textareaRef}
                focused={!isStreaming && !dialogOpen}
                placeholder={isStreaming ? "处理中..." : "输入指令或需求..."}
                initialValue={inputValue}
                onContentChange={() => {
                  const next = textareaRef.current?.plainText ?? "";
                  setInputValue(next);
                  if (next.trimStart().startsWith("/")) setPaletteIdx(0);
                }}
                onSubmit={() => {
                  const text = textareaRef.current?.plainText ?? inputValue;
                  void submitText(text);
                }}
                style={{ flexGrow: 1, height: inputHeight, backgroundColor: C.bg }}
              />
            )}
          </box>
        </box>
      </box>
      )}

      {/* Classic: status (online / 上下文 / Build…) BELOW the dialog */}
      <box style={{ flexShrink: 0, paddingLeft: 1, paddingRight: 1, height: 1, backgroundColor: C.bg }}>
        <text>
          {statusSegments.map((seg, i) => (
            <span key={seg.key}>
              {i > 0 ? <span fg={C.borderDim}>{" │ "}</span> : null}
              <span fg={seg.fg} attributes={seg.bold ? 1 : 0}>
                {seg.text}
              </span>
            </span>
          ))}
        </text>
      </box>
    </box>
  );
}
