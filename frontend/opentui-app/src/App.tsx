import { useCallback, useEffect, useRef, useState } from "react";
import type { ScrollBoxRenderable, TextareaRenderable } from "@opentui/core";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import { cancelActiveRequest, fetchStatus, sendChatMessage, sendCommand } from "./chatApi.ts";
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
import { MODE_COLORS, MODES, type ChatMessage, type Mode, type StatusInfo } from "./types.ts";
import { WORDMARK, WELCOME_LINES, centerPad } from "./brand.ts";

function cycleMode(mode: Mode): Mode {
  const idx = MODES.indexOf(mode);
  return MODES[(idx + 1) % MODES.length];
}

function WelcomeBanner({ cols }: { cols: number }) {
  return (
    <box style={{ flexDirection: "column", paddingTop: 1, paddingBottom: 1, width: "100%" }}>
      {WORDMARK.map((line, i) => (
        <text key={`wm-${i}`} fg={i === 0 ? C.brandLight : C.brandHot} attributes={1}>
          {centerPad(line, cols)}
        </text>
      ))}
      <box style={{ height: 1 }} />
      <text fg={C.brandLight}>{centerPad("✦ General-Purpose AI Agent ✦", cols)}</text>
      <box style={{ height: 1 }} />
      {WELCOME_LINES.map((row, i) => (
        <text key={`w-${i}`} fg={row.fg}>
          {row.text}
        </text>
      ))}
    </box>
  );
}

export default function App() {
  const { width } = useTerminalDimensions();
  const cols = width || 80;
  const [mode, setMode] = useState<Mode>("build");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [progress, setProgress] = useState("");
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [sticky, setSticky] = useState<StickyState>(createStickyState());
  const [inputValue, setInputValue] = useState("");
  const textareaRef = useRef<TextareaRenderable>(null);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingTogglePendingRef = useRef(false);
  const stickyRef = useRef(sticky);
  stickyRef.current = sticky;

  const model = status?.model || process.env.RXYCODE_MODEL || "default";
  const thinkingLive = isStreaming && thinkingExpanded;

  useEffect(() => {
    void fetchStatus(setStatus);
    const iv = setInterval(() => void fetchStatus(setStatus), 30000);
    return () => clearInterval(iv);
  }, []);

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

  const submitText = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed || isStreaming) return;

      if (trimmed === "/clear") {
        setMessages([]);
        setProgress("");
        reengageSticky();
        setInputValue("");
        textareaRef.current?.setText("");
        return;
      }
      if (trimmed === "/build" || trimmed === "/plan" || trimmed === "/compose") {
        setMode(trimmed.slice(1) as Mode);
        setInputValue("");
        textareaRef.current?.setText("");
        return;
      }
      if (trimmed === "/thinking") {
        await toggleThinking();
        setInputValue("");
        textareaRef.current?.setText("");
        return;
      }
      if (trimmed === "/help") {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-sys`,
            role: "system",
            content: "Commands: /clear /build /plan /compose /thinking /help",
            timestamp: Date.now(),
          },
        ]);
        setInputValue("");
        textareaRef.current?.setText("");
        return;
      }

      reengageSticky();
      setInputValue("");
      textareaRef.current?.setText("");

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
        },
        controller.signal,
      );
      abortRef.current = null;
      textareaRef.current?.focus();
    },
    [isStreaming, mode, reengageSticky, toggleThinking],
  );

  useKeyboard((key) => {
    if (key.name === "tab" && !key.shift) {
      setMode((m) => cycleMode(m));
      return;
    }
    if (key.ctrl && key.name === "t") {
      void toggleThinking();
      return;
    }
    if (key.name === "return" && !key.shift && !key.meta && !key.ctrl) {
      const text = textareaRef.current?.plainText ?? inputValue;
      if (text.trim() && !isStreaming && !text.includes("\n")) {
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
      textareaRef.current?.focus();
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
      textareaRef.current?.focus();
    }
  });

  const visibleMessages = messages.filter((m) => {
    if (m.role === "thinking" && !thinkingExpanded && !m.live) return false;
    return true;
  });

  const borderColor = MODE_COLORS[mode] || C.brandHot;
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
    modeColor: borderColor,
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
        <text>
          <span fg={C.brandLight} attributes={1}>
            {"  "}RxyCode v1.1.0
          </span>
          <span fg="#555555">{" · "}</span>
          <span fg={borderColor} attributes={1}>
            {mode}
          </span>
          <span fg="#555555">{" · "}</span>
          <span fg={C.brandHot}>{model}</span>
          {thinkingLive ? <span fg={C.thinking}>{" · 思考中"}</span> : null}
        </text>
      </box>

      <scrollbox
        ref={scrollRef}
        stickyScroll={stickyEnabled}
        stickyStart="bottom"
        flexGrow={1}
        style={{
          rootOptions: { flexGrow: 1, border: false, backgroundColor: C.bg },
          viewportOptions: { flexGrow: 1, backgroundColor: C.bg },
          contentOptions: { flexGrow: 1, backgroundColor: C.bg },
          scrollbarOptions: {
            showArrows: false,
            trackOptions: {
              foregroundColor: C.brandHot,
              backgroundColor: C.surface0,
            },
          },
        }}
      >
        {visibleMessages.length === 0 ? (
          <WelcomeBanner cols={cols} />
        ) : (
          visibleMessages.map((msg) => (
            <box key={msg.id} style={{ width: "100%", paddingLeft: 1, paddingRight: 1 }}>
              <text fg={messageFg(msg.role)}>{formatMessageLine(msg)}</text>
            </box>
          ))
        )}
      </scrollbox>

      {progress ? (
        <box style={{ flexShrink: 0, paddingLeft: 1, height: 1 }}>
          <text fg={C.yellow}>{progress}</text>
        </box>
      ) : null}

      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor,
          borderStyle: "rounded",
          paddingLeft: 1,
          paddingRight: 1,
          backgroundColor: C.bg,
          minHeight: 3,
        }}
      >
        <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
          <box style={{ flexDirection: "row", width: "100%" }}>
            <text fg={borderColor} attributes={1}>
              {" "}
              {mode}{" "}
            </text>
            <text fg={C.overlay2}>{"· "}</text>
            <text fg={C.mauve}>{formatInputHint(isStreaming)}</text>
            {isStreaming ? <text fg={C.yellow}>{" ESC 取消"}</text> : null}
          </box>
          <box style={{ flexDirection: "row", width: "100%" }}>
            <text fg={borderColor} attributes={1}>
              {"> "}
            </text>
            <textarea
              ref={textareaRef}
              focused={!isStreaming}
              placeholder={isStreaming ? "处理中..." : "输入指令或需求..."}
              initialValue={inputValue}
              onContentChange={() => {
                setInputValue(textareaRef.current?.plainText ?? "");
              }}
              onSubmit={() => {
                const text = textareaRef.current?.plainText ?? inputValue;
                void submitText(text);
              }}
              style={{ flexGrow: 1, height: 1, backgroundColor: C.bg }}
            />
          </box>
        </box>
      </box>

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
