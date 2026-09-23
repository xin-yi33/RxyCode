import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { appendFileSync } from "node:fs";
import type { ScrollBoxRenderable, TextareaRenderable, Selection } from "@opentui/core";
import { decodePasteBytes, stripAnsiSequences } from "@opentui/core";
import {
  useKeyboard,
  usePaste,
  useRenderer,
  useSelectionHandler,
  useTerminalDimensions,
} from "@opentui/react";
import {
  cancelActiveRequest,
  fetchStatus,
  invokeSubagent,
  listChildSessions,
  openChildSession,
  openParentSession,
  respondApproval,
  respondQuestion,
  sendChatMessage,
  sendCommand,
  steerTurn,
} from "./chatApi.ts";
import { resolveTransportKind } from "./transport/config.ts";
import { startStdioWarmOnOpen } from "./transport/stdioTransport.ts";
import { ApprovalDialog, type ApprovalInfo } from "./ApprovalDialog.tsx";
import { QuestionDialog } from "./QuestionDialog.tsx";
import type { QuestionInfo, QuestionReply } from "./questionInfo.ts";
import { classifyInput, formatCommandResult } from "./commandRouter.ts";
import { parseMention } from "./mention.ts";
import { formatChildNavigation } from "./childNavigation.ts";
import { filterCommands, resolveSlashSubmit, AVAILABLE_COMMANDS, type Command, isBareModelPickerCommand } from "./commands.ts";
import { APP_VERSION, formatElapsedSuffix, formatInputHint, formatMessageLine, hasThinkingChain, messageFg, shouldRenderThought } from "./format.ts";
import { EFFORT_CHIP_FG, formatComposerEffortChip } from "./dialog/effortPicker.ts";
import { ElapsedTimer } from "./lib/elapsedTimer.ts";
import { sanitizeCopiedText } from "./lib/copySanitize.ts";
import {
  applyThoughtExpandedOverride,
  cycleThinkingDisplay,
  setThoughtExpandedOverride,
  thinkingDisplayExpanded,
  thoughtShowsBody,
} from "./lib/thinkingDisplay.ts";
import { cycleToolCardsDefault } from "./lib/toolCardDisplay.ts";
import { CHAT_PROMPT_KEY_BINDINGS } from "./promptKeyBindings.ts";
import { isPromptNewlineKey, isPromptSubmitKey, normalizePromptSubmitText } from "./promptSubmitKey.ts";
import { buildStatusSegments, formatStatusBarText } from "./statusBar.ts";
import { CHAT_SCROLLBOX_STYLE } from "./chatLayout.ts";
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
  welcomeRowsForSetup,
  WORDMARK,
  BRAND_LIGHT,
  BRAND_HOT,
  BRAND_MUTED,
  LOGO_FIELD_BG,
  logoInkForRow,
} from "./brand.ts";
import { decideModelSetup } from "./modelSetup.ts";
import { probeModels } from "./dialog/api.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "./scroll.ts";
import { looksLikeMarkdown, MarkdownView } from "./Markdown.tsx";
import { applyComposerMarkdownArg, composerMarkdownEnabled } from "./lib/markdownDisplay.ts";
import { ToolCard } from "./ToolCard.tsx";
import { isPlanMdPath, shouldHideToolCard } from "./lib/toolDisplay.ts";
import {
  inputVisibleLines,
  needsInputScroll,
  numInputLines,
  stringWidth,
  wrapContentLines,
} from "./layout.ts";
import { DialogOutlet } from "./dialog/DialogHost.tsx";
import { useSettingsDialogs } from "./dialog/useSettingsDialogs.tsx";
import { enqueueFollowup, FOLLOWUP_LIMIT, putBackFollowup, removeFollowup, takeFollowupById, takeNextFollowup, type FollowupItem } from "./followupQueue.ts";
import { FollowupQueueBar } from "./FollowupQueueBar.tsx";
import { PlanPane } from "./PlanPane.tsx";
import type { PlanDoc } from "./planDoc.ts";
import {
  classifyPlanComposer,
  commentPlanPrompt,
  implementPlanPrompt,
  isPlanShortcutKey,
  requestChangesPrompt,
  type PlanAction,
} from "./planActions.ts";

function cycleMode(mode: Mode): Mode {
  const idx = MODES.indexOf(mode);
  return MODES[(idx + 1) % MODES.length];
}

function isPlanFileTool(msg: ChatMessage): boolean {
  if (msg.role !== "tool") return false;
  const blob = `${msg.toolName || ""} ${msg.toolArgs || ""} ${msg.content || ""}`;
  return isPlanMdPath(blob) || /plan\.md/i.test(blob);
}

const SUBTITLE_CORE = "General-Purpose AI Agent";
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

function WelcomeBanner({ cols, needsModelSetup }: { cols: number; needsModelSetup: boolean }) {
  const welcomeRows = welcomeRowsForSetup(needsModelSetup);
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
      {welcomeRows.map((row, i) => (
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

function ThinkingGlyph({ done, expanded }: { done?: boolean; expanded: boolean }) {
  const [spinnerIdx, setSpinnerIdx] = useState(0);
  useEffect(() => {
    if (done || expanded) return;
    const iv = setInterval(() => setSpinnerIdx((prev) => (prev + 1) % SPINNER_FRAMES.length), 80);
    return () => clearInterval(iv);
  }, [done, expanded]);
  const glyph = expanded ? "-" : done ? "+" : SPINNER_FRAMES[spinnerIdx];
  return (
    <span fg={C.yellow} attributes={1}>
      {"  "}
      {glyph}
    </span>
  );
}

function ThoughtMessage({
  msg,
  onToggle,
  wrapW,
}: {
  msg: ChatMessage;
  onToggle: (id: string) => void;
  wrapW: number;
}) {
  const done = Boolean(msg.done);
  const expanded = thoughtShowsBody(msg);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (done) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [done]);
  const elapsed = new ElapsedTimer(msg.timestamp).format(done ? msg.endedAt ?? now : now);
  const chain = hasThinkingChain(msg.content);
  let lines: string[] = [];
  let clipped = 0;
  if (expanded) {
    const body = chain
      ? msg.content
      : done
        ? "已思考完毕"
        : "正在思考中...";
    const allLines = wrapContentLines(body, Math.max(8, wrapW - 6)).filter((l) => l.trim());
    if (done) {
      // Keep the finished body. Do not replace these lines with an empty
      // placeholder when the Thought settles.
      lines =
        allLines.length <= MAX_EXPANDED_DONE_THINKING_LINES
          ? allLines
          : allLines.slice(-MAX_EXPANDED_DONE_THINKING_LINES);
    } else {
      lines = allLines.slice(-MAX_STREAMING_THINKING_LINES);
    }
    clipped = allLines.length - lines.length;
  }
  return (
    <box
      style={{ flexDirection: "column", width: "100%", paddingLeft: 1, backgroundColor: C.bg }}
    >
      <box onMouseDown={() => onToggle(msg.id)}>
        <text>
          <ThinkingGlyph done={done} expanded={expanded} />
          <span fg={C.yellow} attributes={1}>
            {" "}
            Thought
          </span>
          <span fg={C.subtext}> {elapsed}</span>
        </text>
      </box>
      {expanded
        ? lines.map((line, i) => (
            <text key={i} fg={C.yellow} selectable={done}>
              {"    "}
              {line}
            </text>
          ))
        : null}
      {expanded && clipped > 0 ? (
        <text fg={C.subtext} selectable={done}>
          {"    "}… (+{clipped} 行)
        </text>
      ) : null}
    </box>
  );
}

/** Left quarter-block — half of a full █ cell, one glyph per bubble row. */
const USER_BAR_GLYPH = "\u258E";

/** OpenCode-style user bubble: panel field + thin bar on every row. */
function UserMessage({
  content,
  modeColor,
  wrapW,
  markdown = true,
}: {
  content: string;
  modeColor: string;
  wrapW: number;
  markdown?: boolean;
}) {
  const rendered = markdown && looksLikeMarkdown(content);
  const lines = wrapContentLines(content, Math.max(8, wrapW - 2));
  const barCount = Math.max(3, (rendered ? content.split(/\r?\n/).length : lines.length) + 2);
  return (
    <box
      style={{
        flexDirection: "row",
        width: "100%",
        backgroundColor: C.userBubble,
      }}
    >
      <box style={{ flexDirection: "column", width: 1, minWidth: 1, maxWidth: 1 }}>
        {Array.from({ length: barCount }, (_, i) => (
          <text key={i} fg={modeColor} selectable={false}>
            {USER_BAR_GLYPH}
          </text>
        ))}
      </box>
      <box
        style={{
          flexGrow: 1,
          paddingLeft: 1,
          paddingRight: 1,
          paddingTop: 1,
          paddingBottom: 1,
          flexDirection: "column",
          backgroundColor: C.userBubble,
        }}
      >
        {rendered ? (
          <MarkdownView content={content} backgroundColor={C.userBubble} />
        ) : (
          lines.map((line, i) => (
            <text key={i} fg={C.text} selectable>
              {line || " "}
            </text>
          ))
        )}
      </box>
    </box>
  );
}

function ChatLine({
  msg,
  modeColor,
  wrapW,
  onToggleThought,
  ctrlHeldRef,
  onToolChanged,
  planBody,
  markdown = true,
}: {
  msg: ChatMessage;
  modeColor: string;
  wrapW: number;
  onToggleThought: (id: string) => void;
  ctrlHeldRef: { current: boolean };
  onToolChanged: () => void;
  planBody?: string;
  markdown?: boolean;
}) {
  if (msg.role === "thinking") {
    if (!shouldRenderThought(msg)) return null;
    return (
      <ThoughtMessage
        msg={applyThoughtExpandedOverride(msg)}
        onToggle={onToggleThought}
        wrapW={wrapW}
      />
    );
  }
  if (msg.role === "user") {
    const frameColor =
      msg.mode && MODE_COLORS[msg.mode] ? MODE_COLORS[msg.mode] : modeColor;
    return <UserMessage content={msg.content} modeColor={frameColor} wrapW={wrapW} markdown={markdown} />;
  }
  if (msg.role === "assistant") {
    if (msg.done && planBody && msg.content === planBody) {
      return null;
    }
    // 流式期间也走 Markdown 增量渲染（与 OpenCode 相同：OpenTUI
    // MarkdownRenderable 本就支持部分内容/未闭合代码围栏，逐 chunk 重渲染）。
    // 废弃代码（2026-09-23）：流式纯文本 + 结束后才编译 Markdown——用户看到
    // 整轮原始标记，且结束瞬间整段重排跳动。
    if (msg.done) {
      return (
        <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
          {markdown ? (
            <MarkdownView content={msg.content} wrapW={wrapW} />
          ) : (
            msg.content.split(/\r?\n/).map((line, i) => (
              <text key={i} fg={C.text} selectable>
                {line || " "}
              </text>
            ))
          )}
        </box>
      );
    }
    return (
      <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
        {markdown && msg.content ? (
          <MarkdownView content={msg.content} wrapW={wrapW} />
        ) : (
          <text fg={messageFg("assistant")} selectable>
            {msg.content}
          </text>
        )}
      </box>
    );
  }
  if (msg.role === "child_session") {
    const statusIcon =
      msg.childStatus === "running" ? "⟳" :
      msg.childStatus === "completed" ? "✓" :
      msg.childStatus === "failed" || msg.childStatus === "cancelled" || msg.childStatus === "denied" ? "✗" :
      msg.childStatus === "created" || msg.childStatus === "queued" ? "◷" :
      "?";
    const depthIndent = "  ".repeat(msg.depth ?? 0);
    return (
      <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1, flexDirection: "column" }}>
        <text selectable>
          <span fg={msg.childStatus === "completed" ? C.green : msg.childStatus === "failed" ? C.yellow : C.teal}>
            {`${depthIndent}${statusIcon} [${msg.agentId || "subagent"}] ${msg.childStatus || "unknown"}`}
          </span>
          <span fg={C.subtext}> {msg.childSessionId ? `(${msg.childSessionId.slice(0, 8)}…)` : ""}</span>
        </text>
        {msg.content ? (
          <text fg={C.overlay2} selectable>
            {`${depthIndent}  ${msg.content}`}
          </text>
        ) : null}
      </box>
    );
  }
  if (msg.role === "tool") {
    if (shouldHideToolCard(msg.toolName, msg.content)) return null;
    return (
      <ToolCard msg={msg} wrapW={wrapW} ctrlHeldRef={ctrlHeldRef} onChanged={onToolChanged} />
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

const TUI_REVISION = "product-steer-queue-1.3";

export default function App() {
  useEffect(() => {
  }, []);
  const { width } = useTerminalDimensions();
  const cols = width || 80;
  const renderer = useRenderer();
  const [mode, setMode] = useState<Mode>("build");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<ApprovalInfo | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<QuestionInfo | null>(null);
  const [progress, setProgress] = useState("");
  const [waitClock, setWaitClock] = useState(() => Date.now());
  useEffect(() => {
    if (!isStreaming) return;
    const timer = setInterval(() => setWaitClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isStreaming]);
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [sticky, setSticky] = useState<StickyState>(createStickyState());
  const [inputValue, setInputValue] = useState("");
  const [paletteIdx, setPaletteIdx] = useState(0);
  const [permissionMode, setPermissionMode] = useState("confirm_all");
  const [copyToast, setCopyToast] = useState(false);
  const copyToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ignoreSelectionCopyRef = useRef(false);
  const selectionWasDragRef = useRef(false);
  const ctrlHeldRef = useRef(false);
  const [toolTick, setToolTick] = useState(0);
  void toolTick;
  const [needsModelSetup, setNeedsModelSetup] = useState(false);
  const autoOpenedModelSetupRef = useRef(false);
  const textareaRef = useRef<TextareaRenderable>(null);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingTogglePendingRef = useRef(false);
  const selectionRef = useRef<Selection | null>(null);
  /** OpenCode-style: first Ctrl+C arms quit; second within window exits. */
  const quitArmedUntilRef = useRef(0);
  const stickyRef = useRef(sticky);
  stickyRef.current = sticky;
  const followupsRef = useRef<FollowupItem[]>([]);
  const [followups, setFollowups] = useState<FollowupItem[]>([]);
  const followupCount = followups.length;
  const isStreamingRef = useRef(false);
  const [planDoc, setPlanDoc] = useState<PlanDoc | null>(null);
  const planDocRef = useRef<PlanDoc | null>(null);
  planDocRef.current = planDoc;
  const [planFocused, setPlanFocused] = useState(false);
  const [planSelectedLine, setPlanSelectedLine] = useState(0);
  const editingFollowupRef = useRef<FollowupItem | null>(null);
  const turnModeRef = useRef<Mode>("build");
  const commentLineRef = useRef<{ line: number; text: string } | null>(null);
  const planSourceIdsRef = useRef<Set<string>>(new Set());
  const planDismissedIdsRef = useRef<Set<string>>(new Set());
  const [mdTick, setMdTick] = useState(0);
  const mdComposerOn = composerMarkdownEnabled() && mdTick >= 0;
  const lastPlanRef = useRef<PlanDoc | null>(null);

  useEffect(() => {
  }, [mode]);

  const scrollAccel = useMemo(() => createScrollAcceleration(), []);

  const model = status?.model || process.env.RXYCODE_MODEL || "unknown";
  const thinkingLive = isStreaming;
  const modeColor = MODE_COLORS[mode] || C.brandHot;
  const modeLabel = MODE_LABELS[mode];

  useEffect(() => {
    void fetchStatus(setStatus);
    void sendCommand("/permission").then((result) => {
      const mode =
        (result && typeof result.permission_mode === "string" && result.permission_mode) ||
        (result && typeof result.mode === "string" && result.mode) ||
        "";
      if (mode) setPermissionMode(mode);
    }).catch(() => {});
    const iv = setInterval(() => void fetchStatus(setStatus), 30000);
    if (resolveTransportKind() === "stdio") {
      startStdioWarmOnOpen();
    }
    return () => clearInterval(iv);
  }, []);

  // Keep the composer focused when the live stream ends. Drain the queue
  // only after session/prompt returns — early Ready must not start a
  // second prompt that stacks notification handlers.
  const turnBusyRef = useRef(false);
  const wasStreamingRef = useRef(false);
  // 2026-09-23: turn start timestamp for the locally-ticked elapsed suffix
  // (see formatElapsedSuffix) — guarantees visible liveness while streaming
  // even when backend heartbeat progress stalls.
  const [streamStartAt, setStreamStartAt] = useState(0);
  isStreamingRef.current = isStreaming;
  useEffect(() => {
    if (!wasStreamingRef.current && isStreaming) {
      setStreamStartAt(Date.now());
    }
    if (wasStreamingRef.current && !isStreaming) {
      setStreamStartAt(0);
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

  const flashCopyToast = useCallback(() => {
    setCopyToast(true);
    if (copyToastTimerRef.current) clearTimeout(copyToastTimerRef.current);
    copyToastTimerRef.current = setTimeout(() => setCopyToast(false), 3000);
  }, []);

  const copyPlain = useCallback(
    (raw: string): boolean => {
      const text = sanitizeCopiedText(raw);
      if (!text) return false;
      try {
        renderer.copyToClipboardOSC52(text);
        flashCopyToast();
        return true;
      } catch {
        return false;
      }
    },
    [flashCopyToast, renderer],
  );

  const copySelection = useCallback(() => {
    const sel = selectionRef.current;
    const text = sel?.getSelectedText?.()?.trim() ?? "";
    if (!text) return false;
    return copyPlain(text);
  }, [copyPlain]);

  /** 复制全部对话文本到剪贴板（解决终端鼠标框选受视口限制、无法全部复制的问题）。 */
  const copyAllMessages = useCallback(() => {
    const lines: string[] = [];
    for (const m of messagesRef.current) {
      if (m.role === "user") lines.push(`> ${m.content}`);
      else if (m.role === "assistant") lines.push(m.content);
      else if (m.role === "thinking") lines.push(`[思考] ${m.content}`);
      else if (m.role === "tool") {
        const name = m.toolName || "tool";
        const status = m.toolStatus || "running";
        const args = m.toolArgs ? ` ${m.toolArgs}` : "";
        lines.push(`[${name} ${status}]${args} ${m.content || ""}`);
      } else if (m.role === "system") lines.push(`[系统] ${m.content}`);
      else if (m.role === "child_session") lines.push(`[子代理 ${m.agentId || ""}] ${m.content}`);
    }
    const text = lines.join("\n").trim();
    if (!text) return false;
    return copyPlain(text);
  }, [copyPlain]);

  useSelectionHandler((sel: Selection) => {
    selectionRef.current = sel;
    if (sel?.isDragging) selectionWasDragRef.current = true;
    // Grok: only y copies the plan. Quit/comment must not copy a click-selection.
    if (ignoreSelectionCopyRef.current) {
      ignoreSelectionCopyRef.current = false;
      selectionWasDragRef.current = false;
      return;
    }
    if (sel && !sel.isDragging && sel.isActive && selectionWasDragRef.current) {
      selectionWasDragRef.current = false;
      const text = sel.getSelectedText?.() ?? "";
      if (text.trim()) copyPlain(text);
    }
    if (!sel?.isActive) selectionWasDragRef.current = false;
  });

  const toggleThinking = useCallback(async () => {
    if (thinkingTogglePendingRef.current) return;
    thinkingTogglePendingRef.current = true;
    try {
      const result = cycleThinkingDisplay();
      setThinkingExpanded(result.expanded);
    } finally {
      thinkingTogglePendingRef.current = false;
    }
  }, []);

  const toggleOneThought = useCallback((id: string) => {
    const current = messagesRef.current.find((m) => m.id === id);
    setMessages((prev) =>
      prev.map((msg) => {
        if (msg.id !== id || msg.role !== "thinking") return msg;
        const next = !Boolean(msg.expanded);
        setThoughtExpandedOverride(id, next);
        return { ...msg, expanded: next };
      }),
    );
    try {
      renderer.clearSelection();
    } catch {
      // ignore
    }
    queueMicrotask(() => {
      try {
        renderer.clearSelection();
      } catch {
        // ignore
      }
    });
  }, [renderer]);

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

  const patchFollowups = useCallback((next: FollowupItem[]) => {
    followupsRef.current = next;
    setFollowups(next);
  }, []);

  const enqueueBusyFollowup = useCallback(
    (raw: string, queuedMode: Mode) => {
      const before = followupsRef.current;
      const next = enqueueFollowup(before, raw, queuedMode);
      if (next.length === before.length) {
        if (before.length >= FOLLOWUP_LIMIT) {
          pushSystem(`队列已满（最多 ${FOLLOWUP_LIMIT} 条），等当前回合结束后再发`);
        }
        return false;
      }
      patchFollowups(next);
      const preview = next[next.length - 1]?.text ?? "";
      pushSystem(`已排队（${next.length}）[${queuedMode}]: ${preview.slice(0, 80)}`);
      return true;
    },
    [patchFollowups, pushSystem],
  );

  const fillComposer = useCallback((text: string) => {
    setInputValue(text);
    try {
      textareaRef.current?.setText(text);
      textareaRef.current?.focus();
    } catch {
      // ignore
    }
  }, []);

  const handleQueueDelete = useCallback(
    (id: string) => {
      patchFollowups(removeFollowup(followupsRef.current, id));
    },
    [patchFollowups],
  );

  const handleQueueEdit = useCallback(
    (id: string) => {
      const taken = takeFollowupById(followupsRef.current, id);
      if (!taken.item) return;
      const draftText = (textareaRef.current?.plainText ?? inputValue).trim();
      const previous = editingFollowupRef.current;
      let next = taken.remaining;
      if (previous && previous.id !== taken.item.id) {
        next = putBackFollowup(next, {
          ...previous,
          text: draftText || previous.text,
        });
      }
      editingFollowupRef.current = taken.item;
      patchFollowups(next);
      fillComposer(taken.item.text);
    },
    [fillComposer, inputValue, patchFollowups],
  );

  const handleQueueSendNow = useCallback(
    (id: string) => {
      const taken = takeFollowupById(followupsRef.current, id);
      if (!taken.item) return;
      patchFollowups(taken.remaining);
      const text = taken.item.text;
      const sendMode = taken.item.mode;
      const restore = () => {
        patchFollowups([taken.item!, ...taken.remaining]);
      };
      void (async () => {
        const canSteer =
          isStreamingRef.current && turnModeRef.current === sendMode;
        if (canSteer) {
          const result = await steerTurn(text, sendMode);
          if (result.ok) {
            if (!result.injected) {
              setMessages((prev) => [
                ...prev,
                {
                  id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                  role: "user" as const,
                  content: text,
                  timestamp: Date.now(),
                  mode: sendMode,
                },
              ]);
            }
            return;
          }
          if (isStreamingRef.current) {
            restore();
            pushSystem(`立即发送失败，仍留在队列: ${result.message}`);
            return;
          }
        }
        void submitTextRef.current?.(text, sendMode);
      })();
    },
    [mode, patchFollowups, pushSystem],
  );

  const applyPlanAction = useCallback(
    (action: PlanAction) => {
      const plan = planDocRef.current;
      if (!plan) return;
      if (action !== "copy") ignoreSelectionCopyRef.current = true;
      if (action === "approve") {
        for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
        setPlanDoc(null);
        setPlanFocused(false);
        setMode("build");
        ignoreSelectionCopyRef.current = true;
        void submitTextRef.current?.(implementPlanPrompt(plan.body), "build", "已批准计划，开始实施");
        return;
      }
      if (action === "quit") {
        ignoreSelectionCopyRef.current = true;
        for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
        setPlanDoc(null);
        setPlanFocused(false);
        setMode("build");
        return;
      }
      if (action === "copy") {
        copyPlain(plan.body);
        return;
      }
      if (action === "request_changes") {
        ignoreSelectionCopyRef.current = true;
        for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
        setPlanDoc(null);
        setPlanFocused(false);
        setMode("plan");
        void submitTextRef.current?.(requestChangesPrompt(plan.body), "plan", "请修订这份计划");
        return;
      }
      const lines = plan.body.split(/\r?\n/);
      commentLineRef.current = {
        line: planSelectedLine + 1,
        text: lines[planSelectedLine] || "",
      };
      setPlanFocused(false);
      fillComposer("");
      pushSystem(`Comment 第 ${planSelectedLine + 1} 行：输入批注后回车`);
    },
    [copyPlain, fillComposer, planSelectedLine, pushSystem],
  );

  const clearInput = useCallback(() => {
    setInputValue("");
    textareaRef.current?.setText("");
    setPaletteIdx(0);
  }, []);

  const statusLine = status
    ? `${status.model || "?"} · ${status.mode || mode} · effort ${formatComposerEffortChip(status.effort)} · ctx ${status.context_used_k ?? 0}k`
    : "offline";
  // 废弃代码（2026-09-21）：status.effort ?? "balanced" 与芯片 default 不一致，禁止再引用。
  // const statusLine = status
  //   ? `${status.model || "?"} · ${status.mode || mode} · effort ${status.effort ?? "balanced"} · ctx ${status.context_used_k ?? 0}k`
  //   : "offline";

  const settingsDialogs = useSettingsDialogs({
    pushSystem,
    setMessages,
    fetchStatus: () => void fetchStatus(setStatus),
    clearInput,
    statusLine,
    activeModel: model,
    setPermissionMode,
    onModelsChanged: async () => {
      const probe = await probeModels();
      if (probe.ok) setNeedsModelSetup(probe.models.length === 0);
    },
    onFallbackCommand: (cmd) => {
      void submitTextRef.current?.(cmd.name);
    },
  });

  const submitTextRef = useRef<((text: string, sendMode?: Mode, displayText?: string) => Promise<void>) | null>(null);

  const { dialogOpen, openPalette, openSession, openModel, openAddModel, routePaletteCommand } =
    settingsDialogs;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let i = 0; i < 10 && !cancelled; i++) {
        const probe = await probeModels();
        if (cancelled) return;
        if (!probe.ok) {
          await new Promise((r) => setTimeout(r, 200));
          continue;
        }
        const decision = decideModelSetup({
          fetchOk: true,
          modelCount: probe.models.length,
          alreadyAutoOpened: autoOpenedModelSetupRef.current,
        });
        setNeedsModelSetup(decision.needsSetup);
        if (decision.shouldAutoOpen) {
          autoOpenedModelSetupRef.current = true;
          openAddModel();
        }
        return;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openAddModel]);

  usePaste((event) => {
    // Nested dialogs own paste (focused search input). Do not preventDefault.
    // Streaming must still accept paste: Enter queues the follow-up.
    if (dialogOpen || pendingApproval || pendingQuestion) return;
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
      if (dialogOpen || pendingApproval || pendingQuestion) {
        textareaRef.current?.blur?.();
      } else {
        textareaRef.current?.focus?.();
      }
    } catch {
      // ignore
    }
  }, [dialogOpen, pendingApproval, pendingQuestion, isStreaming]);

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
        if (name === "/copy") {
          const ok = copyAllMessages();
          pushSystem(ok ? "已复制全部对话到剪贴板" : "没有可复制的内容");
          clearInput();
          return;
        }
        if (name === "/build" || name === "/plan" || name === "/compose") {
          setMode(name.slice(1) as Mode);
          clearInput();
          return;
        }
        if (name === "/view-plan") {
          const saved = lastPlanRef.current;
          if (!saved) {
            pushSystem("还没有可查看的计划。先在 Plan 模式发一条规划任务。");
          } else {
            setPlanDoc(saved);
            setPlanFocused(false);
          }
          clearInput();
          return;
        }
        if (name === "/thinking") {
          await toggleThinking();
          clearInput();
          return;
        }
        if (name === "/tools") {
          const result = cycleToolCardsDefault();
          pushSystem(`工具结果默认${result.expanded ? "展开" : "折叠"}（点击工具名可单独开合）`);
          setToolTick((n) => n + 1);
          clearInput();
          return;
        }
        if (name === "/markdown") {
          const result = applyComposerMarkdownArg(args);
          pushSystem(result.enabled ? "对话 Markdown 渲染：开" : "对话 Markdown 渲染：关（普通纯文本）");
          setMdTick((n) => n + 1);
          clearInput();
          return;
        }
        if (name === "/children") {
          try {
            const children = await listChildSessions();
            pushSystem(
              children.length === 0
                ? "No child sessions are active."
                : children.map((child, index) =>
                    `${index + 1}. @${child.agent_id ?? "child"} · ${child.status ?? "unknown"} · ${child.session_id}`,
                  ).join("\n"),
            );
          } catch (error) {
            pushSystem(`Unable to list child sessions: ${error instanceof Error ? error.message : String(error)}`);
          }
          clearInput();
          return;
        }
        if (name === "/child") {
          if (!args) {
            pushSystem("Usage: /child <session_id|index>");
          } else {
            try {
              const result = await openChildSession(args);
              pushSystem(result.ok && result.entry
                ? formatChildNavigation(result.entry, result.events)
                : result.message);
            } catch (error) {
              pushSystem(`Unable to open child session: ${error instanceof Error ? error.message : String(error)}`);
            }
          }
          clearInput();
          return;
        }
        if (name === "/parent") {
          try {
            const result = await openParentSession();
            pushSystem(result.message);
          } catch (error) {
            pushSystem(`Unable to return to parent session: ${error instanceof Error ? error.message : String(error)}`);
          }
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
            "/effort",
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

      // 废弃代码（2026-09-21）：bare /permission /model /effort /addmodel 已由上方
      // routePaletteCommand 单源处理。再调 openX() 会双开或盖掉 /effort overlay。
      // if (name === "/permission" && !args) {
      //   openPermission();
      //   clearInput();
      //   return;
      // }
      if (name === "/session" || name === "/list-chats" || name === "/load-chat" || name === "/save-chat") {
        if (name === "/save-chat") {
          pushSystem("会话已自动保存，用 /session 查看");
          clearInput();
          return;
        }
        openSession();
        clearInput();
        return;
      }
      // 废弃代码（2026-09-21）：bare /model /models 由 isBareModelPickerCommand → openModel，
      // 或 catalog → routePaletteCommand。禁止再引用下面这段。
      // if ((name === "/model" || name === "/models") && !args) {
      //   openModel();
      //   clearInput();
      //   return;
      // }
      // if (name === "/effort" && !args) {
      //   openEffort();
      //   clearInput();
      //   return;
      // }
      // if (name === "/addmodel" && !args) {
      //   openAddModel();
      //   clearInput();
      //   return;
      // }

      const cmd = args ? `${name} ${args}` : name;
      const toSend = cmd === "/model" ? "/models" : cmd;
      const result = await sendCommand(toSend);
      if (name === "/thinking") {
        setThinkingExpanded(thinkingDisplayExpanded());
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
      copyAllMessages,
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
      if (ok && decision === "always_allow_level") {
        setPermissionMode("full_auto");
        void sendCommand("/permission full_auto").then((result) => {
          const mode =
            (result && typeof result.permission_mode === "string" && result.permission_mode) ||
            "full_auto";
          setPermissionMode(mode);
        }).catch(() => {});
      }
      if (!ok) {
        pushSystem(`Approval failed for ${pending.tool}`);
      }
    },
    [pendingApproval, permissionMode, pushSystem],
  );

  const onQuestionRequest = useCallback((info: QuestionInfo | null) => {
    setPendingQuestion((prev) => {
      if (info === null) return null;
      if (prev && prev.questionId === info.questionId) return prev;
      return info;
    });
    if (info) setProgress(`等待回答: ${info.question}`);
  }, []);

  const onQuestionResponse = useCallback(
    async (reply: QuestionReply) => {
      const pending = pendingQuestion;
      if (!pending) return;
      setPendingQuestion(null);
      const ok = await respondQuestion(pending.questionId, reply);
      if (!ok) {
        pushSystem("Question response failed");
      }
    },
    [pendingQuestion, pushSystem],
  );

  const submitText = useCallback(
    async (raw: string, sendMode?: Mode, displayText?: string) => {
      const activeMode = sendMode ?? mode;
      const resolved = raw.trimStart().startsWith("/")
        ? resolveSlashSubmit(raw, paletteIdx)
        : raw;
      const classified = classifyInput(resolved);
      if (classified.kind === "chat" && !classified.text) return;
      const phaseFPromptCommands = new Set([
        "/solo",
        "/team",
        "/team-multi",
        "/explore",
        "/why-mode",
        "/agents",
      ]);
      if (turnBusyRef.current) {
        const startsTurn =
          classified.kind === "chat" ||
          (classified.kind === "command" && phaseFPromptCommands.has(classified.name));
        if (startsTurn) {
          let queued = classified.kind === "command" ? classified.raw : classified.text;
          if (classified.kind === "chat" && planDocRef.current && sendMode == null) {
            queued = requestChangesPrompt(planDocRef.current.body, queued);
            for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
            setPlanDoc(null);
            setPlanFocused(false);
          }
          if (enqueueBusyFollowup(queued, activeMode)) {
            clearInput();
          }
          return;
        }
      }

      if (classified.kind === "command") {
        if (!phaseFPromptCommands.has(classified.name)) {
          if (isBareModelPickerCommand(classified.name, classified.args)) {
            openModel();
            clearInput();
            return;
          }
          await runLocalOrRemoteCommand(
            classified.name,
            classified.args,
            classified.raw,
            classified.local,
          );
          return;
        }
      }

      const trimmed = classified.kind === "command" ? classified.raw : classified.text;
      let outgoing = trimmed;
      let outgoingMode = activeMode;
      // sendMode != null: approve / request-changes / queue drain already chose mode.
      // Do not re-classify the injected plan prompt as a composer revise.
      if (classified.kind === "chat" && planDocRef.current && sendMode == null) {
        const intent = classifyPlanComposer(trimmed);
        const plan = planDocRef.current;
        if (intent.kind === "approve" || intent.kind === "start_build") {
          for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
          setPlanDoc(null);
          setPlanFocused(false);
          setMode("build");
          outgoing = implementPlanPrompt(plan.body);
          outgoingMode = "build";
        } else if (intent.kind === "copy") {
          copyPlain(plan.body);
          clearInput();
          return;
        } else if (intent.kind === "quit") {
          for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
          setPlanDoc(null);
          setPlanFocused(false);
          setMode("build");
          clearInput();
          return;
        } else if (intent.kind === "comment") {
          const lines = plan.body.split(/\r?\n/);
          commentLineRef.current = {
            line: planSelectedLine + 1,
            text: lines[planSelectedLine] || "",
          };
          clearInput();
          pushSystem(`Comment 第 ${planSelectedLine + 1} 行：输入批注后回车`);
          return;
        } else if (commentLineRef.current) {
          for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
          setPlanDoc(null);
          setPlanFocused(false);
          outgoing = commentPlanPrompt(
            trimmed,
            commentLineRef.current.line,
            commentLineRef.current.text,
          );
          commentLineRef.current = null;
          outgoingMode = "plan";
          setMode("plan");
        } else {
          // Free-form notes = Grok request-changes: close the pager, then revise.
          for (const id of planSourceIdsRef.current) planDismissedIdsRef.current.add(id);
          setPlanDoc(null);
          setPlanFocused(false);
          outgoing = requestChangesPrompt(plan.body, trimmed);
          outgoingMode = "plan";
          setMode("plan");
        }
      }
      editingFollowupRef.current = null;
      turnModeRef.current = outgoingMode;
      reengageSticky();
      clearInput();

      const controller = new AbortController();
      abortRef.current = controller;

      const mention = parseMention(trimmed);
      if (mention) {
        const { agentId, prompt } = mention;
        const userMsg = {
          id: `user-${Date.now()}`,
          role: "user" as const,
          content: outgoing,
          timestamp: Date.now(),
          mode: outgoingMode,
        };
        setMessages((prev) => [...prev, userMsg]);
        setIsStreaming(true);
        turnBusyRef.current = true;
        try {
          const result = await invokeSubagent(agentId, prompt);
          const childMsg = {
            id: `child-${Date.now()}`,
            role: "child_session" as const,
            content: result.summary || result.error?.message || "子代理无返回",
            childSessionId: result.child_session_id,
            childStatus: result.status,
            agentId,
            timestamp: Date.now(),
            done: true,
          };
          setMessages((prev) => [...prev, childMsg]);
        } catch (e) {
          setMessages((prev) => [
            ...prev,
            {
              id: `child-${Date.now()}`,
              role: "child_session" as const,
              content: e instanceof Error ? e.message : String(e),
              childStatus: "failed",
              agentId,
              timestamp: Date.now(),
              done: true,
            },
          ]);
        } finally {
          setIsStreaming(false);
          turnBusyRef.current = false;
          abortRef.current = null;
        }
        return;
      }

      turnBusyRef.current = true;
      try {
        await sendChatMessage(
          outgoing,
          outgoingMode,
          {
            onMessages: setMessages,
            onStreaming: setIsStreaming,
            onStatus: setStatus,
            onProgress: setProgress,
            onApprovalRequest,
            onQuestionRequest,
            onPlan: (doc) => {
              const last = [...messagesRef.current].reverse().find((m) => m.role === "assistant");
              if (last) planSourceIdsRef.current.add(last.id);
              lastPlanRef.current = doc;
              setPlanDoc(doc);
              setPlanFocused(false);
              setPlanSelectedLine(0);
            },
          },
          controller.signal,
          displayText?.trim() || (outgoing !== trimmed ? trimmed : undefined),
        );
      } finally {
        turnBusyRef.current = false;
      }
      setPendingApproval(null);
      setPendingQuestion(null);
      abortRef.current = null;
      textareaRef.current?.focus();
      const taken = takeNextFollowup(followupsRef.current);
      if (taken.item) {
        followupsRef.current = taken.remaining;
        setFollowups(taken.remaining);
        void submitTextRef.current?.(taken.item.text, taken.item.mode);
      }
    },
    [clearInput, copyPlain, enqueueBusyFollowup, isStreaming, mode, onApprovalRequest, onQuestionRequest, openModel, paletteIdx, planSelectedLine, pushSystem, reengageSticky, runLocalOrRemoteCommand],
  );

  const submitFromInput = useCallback(() => {
    if (dialogOpen || pendingApproval || pendingQuestion) return;
    const plain = textareaRef.current?.plainText ?? "";
    const text = normalizePromptSubmitText(plain || inputValue);
    if (!text) return;
    void submitText(text);
  }, [dialogOpen, inputValue, pendingApproval, pendingQuestion, submitText]);

  const onPromptKeyDown = useCallback(
    (key: { name?: string; sequence?: string; raw?: string; shift?: boolean; meta?: boolean; ctrl?: boolean; super?: boolean; preventDefault?: () => void }) => {
      if (isPromptNewlineKey(key)) {
        key.preventDefault?.();
        textareaRef.current?.newLine?.();
        setInputValue(textareaRef.current?.plainText ?? `${inputValue}\n`);
        return;
      }
      if (!isPromptSubmitKey(key)) return;
      const text = normalizePromptSubmitText(
        textareaRef.current?.plainText ?? inputValue,
      );
      if (!text || dialogOpen || pendingApproval || pendingQuestion) return;
      // Stop textarea default newline / submit double-fire; we own submission.
      key.preventDefault?.();
      submitFromInput();
    },
    [dialogOpen, inputValue, pendingApproval, pendingQuestion, submitFromInput],
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
    ctrlHeldRef.current = Boolean(key.ctrl);
    if (pendingApproval || pendingQuestion || dialogOpen) {
      // Nested dialogs / approval / question own keyboard; Ctrl+P only opens when closed.
      if (dialogOpen && !(key.ctrl && key.name === "p")) return;
      if ((pendingApproval || pendingQuestion) && !(key.ctrl && key.name === "p")) return;
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

    if (
      planDoc &&
      !inputValue.trim() &&
      !isStreaming &&
      !key.ctrl &&
      !key.meta &&
      !key.shift
    ) {
      const action = isPlanShortcutKey(key.name) || isPlanShortcutKey(key.sequence);
      if (action) {
        key.preventDefault?.();
        applyPlanAction(action);
        return;
      }
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
    if (
      slashSuggestions.length > 0 &&
      (key.name === "up" || key.name === "down") &&
      !key.ctrl &&
      !key.meta
    ) {
      key.preventDefault();
      setPaletteIdx((prev) => {
        const n = slashSuggestions.length;
        if (key.name === "up") return (prev - 1 + n) % n;
        return (prev + 1) % n;
      });
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
        setIsStreaming(false);
        setProgress("");
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
    if (isPromptNewlineKey(key)) {
      key.preventDefault?.();
      textareaRef.current?.newLine?.();
      setInputValue(textareaRef.current?.plainText ?? `${inputValue}\n`);
      return;
    }
    const promptText = textareaRef.current?.plainText ?? inputValue;
    if (isPromptSubmitKey(key) && !promptText.trim()) {
      key.preventDefault();
      return;
    }
    if (isPromptSubmitKey(key)) {
      const text = normalizePromptSubmitText(
        textareaRef.current?.plainText ?? inputValue,
      );
      if (text) {
        key.preventDefault?.();
        submitFromInput();
      }
      return;
    }
    if (key.name === "escape") {
      if (isStreaming && abortRef.current) {
        setIsStreaming(false);
        setProgress("");
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

  // Hide the streamed assistant dump only when a real plan.md write/edit card exists.
  const hasPlanFileCard = messages.some(isPlanFileTool);
  const visibleMessages = messages.filter((m) => {
    if (hasPlanFileCard && planSourceIdsRef.current.has(m.id)) return false;
    return true;
  });
  useEffect(() => {
  }, [messages.length, visibleMessages.length, hasPlanFileCard, planDoc]);

  const stickyEnabled = shouldAutoStick(sticky);
  // 废弃代码（2026-09-21）：void formatHeaderLine(mode, model, thinkingLive)
  // 三参签名仍由 format.ts 保留；顶栏芯片禁止再用该字符串。
  // 废弃代码（2026-09-21）：composer 再画 model · effort 会挤掉 Ready、挡住 textarea 复制。档位只在顶栏。
  const effortChip = formatComposerEffortChip(status?.effort);

  const teamRole = progress.match(/^\[([^\]]+)\]/)?.[1] ?? "";
  const teamBudget = progress.match(/(\d+(?:\.\d+)?k?\/\d+(?:\.\d+)?k?)\s*$/)?.[1] ?? "";
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
    teamRole: teamRole || undefined,
    teamBudget: teamBudget || undefined,
  });
  void formatStatusBarText;
  const statusUsed = statusSegments.reduce(
    (w, seg, i) => w + stringWidth(seg.text) + (i > 0 ? 3 : 0),
    0,
  );
  const statusPad = Math.max(0, cols - 2 - statusUsed);
  const showProgressSlot = Boolean(progress) || isStreaming || Boolean(planDoc && !dialogOpen);
  // 等待终端的秒数跟工具卡同一起点。服务端那串（Ns）会被另一条 bash 或积压的进度盖掉，
  // 出现卡片 1 分 36 秒、旁边却是 9s。
  // 废弃代码（2026-09-22）：直接显示 progress 里的秒数。
  const runningBash = [...messages].reverse().find(
    (m) =>
      m.role === "tool" &&
      (m.toolStatus || "running") === "running" &&
      /^(bash|shell)$/i.test(m.toolName || ""),
  );
  const bashWaitSec = runningBash
    ? Math.max(0, Math.floor((waitClock - runningBash.timestamp) / 1000))
    : null;
  const progressForLine =
    bashWaitSec != null && progress.includes("等待终端返回")
      ? bashWaitSec >= 1
        ? `等待终端返回（${bashWaitSec}s）…`
        : "等待终端返回…"
      : progress;
  // 2026-09-23: locally-ticked elapsed — the status line must visibly change
  // every second while streaming, even if backend heartbeats stall (issue:
  // "log 显示在运行，TUI 看不见在运行").  A stalled backend heartbeat next to
  // a running local clock is itself the diagnostic.
  const turnElapsedSec =
    isStreaming && streamStartAt > 0
      ? Math.max(0, Math.floor((waitClock - streamStartAt) / 1000))
      : null;
  const elapsedSuffix = formatElapsedSuffix(turnElapsedSec);
  const progressLine = planDoc && !dialogOpen && !isStreaming
    ? (cols < 28 ? "等待计划审批" : "Waiting on plan approval")
    : progressForLine
      ? (() => {
          const full = progressForLine + elapsedSuffix;
          return full.length > cols ? `${full.slice(0, Math.max(1, cols - 3))}…` : full;
        })()
      : turnElapsedSec != null
        ? `思考中${elapsedSuffix}`
        : " ";


  return (
    <box
      style={{
        flexDirection: "column",
        width: "100%",
        height: "100%",
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexShrink: 0, paddingLeft: 1, paddingRight: 1, height: copyToast ? 3 : 1, flexDirection: "row" }}>
        <box style={{ flexGrow: 1 }}>
          <text selectable>
            <span fg={BRAND_LIGHT} attributes={1}>
              {"  "}RxyCode v{APP_VERSION}
            </span>
            <span fg={BRAND_MUTED}>{" · "}</span>
            <span fg={modeColor} attributes={1}>
              {modeLabel}
            </span>
            <span fg={BRAND_MUTED}>{" · "}</span>
            <span fg={modeColor}>{model}</span>
            <span fg={BRAND_MUTED}>{" · "}</span>
            <span fg={EFFORT_CHIP_FG} attributes={1}>{effortChip}</span>
            {thinkingLive ? <span fg={C.thinking}>{" · 思考中"}</span> : null}
          </text>
        </box>
        {copyToast ? (
          <box
            style={{
              flexDirection: "row",
              flexShrink: 0,
              backgroundColor: C.userBubble,
            }}
          >
            <box style={{ flexDirection: "column", width: 1, minWidth: 1, maxWidth: 1 }}>
              {[" ", " ", " "].map((_, i) => (
                <text key={i} fg={modeColor} selectable={false}>
                  {USER_BAR_GLYPH}
                </text>
              ))}
            </box>
            <box style={{ flexDirection: "column", backgroundColor: C.userBubble }}>
              <text fg={C.userBubble}>{" "}</text>
              <text fg={C.text} bg={C.userBubble}>
                {" Copied to clipboard "}
              </text>
              <text fg={C.userBubble}>{" "}</text>
            </box>
            <box style={{ flexDirection: "column", width: 1, minWidth: 1, maxWidth: 1 }}>
              {[" ", " ", " "].map((_, i) => (
                <text key={`r${i}`} fg={modeColor} selectable={false}>
                  {USER_BAR_GLYPH}
                </text>
              ))}
            </box>
          </box>
        ) : null}
      </box>

      <scrollbox
        ref={scrollRef}
        stickyScroll={stickyEnabled}
        stickyStart="bottom"
        flexGrow={1}
        scrollAcceleration={scrollAccel}
        style={{
          ...CHAT_SCROLLBOX_STYLE,
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
          <WelcomeBanner cols={cols} needsModelSetup={needsModelSetup} />
        ) : (
          visibleMessages.map((msg) => (
            <box key={msg.id} style={{ width: "100%", paddingTop: 1 }}>
              <ChatLine
                msg={msg}
                modeColor={modeColor}
                wrapW={Math.max(20, cols - 8)}
                onToggleThought={toggleOneThought}
                ctrlHeldRef={ctrlHeldRef}
                onToolChanged={() => setToolTick((n) => n + 1)}
                planBody={planDoc?.body}
                markdown={mdComposerOn}
              />
            </box>
          ))
        )}
      </scrollbox>

      {planDoc && !dialogOpen ? (
        <PlanPane
          doc={planDoc}
          focused={planFocused}
          captureEsc={!isStreaming}
          borderColor={MODE_COLORS.plan}
          selectedLine={planSelectedLine}
          onSelectLine={setPlanSelectedLine}
          onFocus={() => setPlanFocused(true)}
          onBlur={() => setPlanFocused(false)}
          onClose={() => applyPlanAction("quit")}
          onAction={applyPlanAction}
        />
      ) : null}

      {showProgressSlot ? (
        <box style={{ flexShrink: 0, paddingLeft: 1, height: 1, overflow: "hidden", backgroundColor: C.bg }}>
          <text fg={C.yellow} wrapMode="none">
            {progressLine}
          </text>
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
            {"  命令建议 (↑↓ 选择 · 回车执行 · Tab 补全)"}
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

      <FollowupQueueBar
        items={followups}
        onSendNow={handleQueueSendNow}
        onEdit={handleQueueEdit}
        onDelete={handleQueueDelete}
      />

      {pendingApproval ? (
        <ApprovalDialog approval={pendingApproval} onDecision={onApprovalDecision} />
      ) : pendingQuestion ? (
        <QuestionDialog question={pendingQuestion} onResponse={onQuestionResponse} />
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
        onMouseDown={() => setPlanFocused(false)}
      >
        <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
          <box style={{ flexDirection: "row", width: "100%" }}>
            <text fg={modeColor} attributes={1}>
              {" "}
              {modeLabel}{" "}
            </text>
            <text fg={C.overlay2}>{"· "}</text>
            <text fg={C.mauve}>{formatInputHint(isStreaming, followupCount)}</text>
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
                  focused={!dialogOpen}
                  placeholder={isStreaming ? "处理中，回车加入队列..." : "输入指令或需求..."}
                  initialValue={inputValue}
                  keyBindings={CHAT_PROMPT_KEY_BINDINGS}
                  onKeyDown={onPromptKeyDown}
                  onContentChange={() => {
                    const next = textareaRef.current?.plainText ?? "";
                    setInputValue(next);
                    if (next.trimStart().startsWith("/")) setPaletteIdx(0);
                  }}
                  onSubmit={submitFromInput}
                  style={{ flexGrow: 1, height: Math.max(inputHeight, numInputLines(inputValue, inputWrapW)), backgroundColor: C.bg }}
                />
              </scrollbox>
            ) : (
              <textarea
                ref={textareaRef}
                focused={!dialogOpen}
                placeholder={isStreaming ? "处理中，回车加入队列..." : "输入指令或需求..."}
                initialValue={inputValue}
                keyBindings={CHAT_PROMPT_KEY_BINDINGS}
                onKeyDown={onPromptKeyDown}
                onContentChange={() => {
                  const next = textareaRef.current?.plainText ?? "";
                  setInputValue(next);
                  if (next.trimStart().startsWith("/")) setPaletteIdx(0);
                }}
                onSubmit={submitFromInput}
                style={{ flexGrow: 1, height: inputHeight, backgroundColor: C.bg }}
              />
            )}
          </box>
        </box>
      </box>
      )}

      {/* Classic: status (online / 上下文 / Build…) BELOW the dialog */}
      <box style={{ flexShrink: 0, paddingLeft: 1, paddingRight: 1, height: 1, width: "100%", overflow: "hidden", backgroundColor: C.bg }}>
        <text wrapMode="none">
          {statusSegments.map((seg, i) => (
            <span key={seg.key}>
              {i > 0 ? <span fg={C.borderDim}>{" │ "}</span> : null}
              <span fg={seg.fg} attributes={seg.bold ? 1 : 0}>
                {seg.text}
              </span>
            </span>
          ))}
          {statusPad > 0 ? <span>{" ".repeat(statusPad)}</span> : null}
        </text>
      </box>
    </box>
  );
}
