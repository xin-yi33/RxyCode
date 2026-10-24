import { useEffect, useMemo, useRef, useState } from "react";
import { useKeyboard, useOnResize, useTerminalDimensions } from "@opentui/react";
import type { ScrollBoxRenderable } from "@opentui/core";
import { C } from "./theme.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "./scroll.ts";

export type ApprovalDecision = "approved" | "rejected" | "always_allow_level";

export interface ApprovalInfo {
  approvalId: string;
  tool: string;
  risk: string;
  args: string;
  /** 2026-10-12 外部工具（如 MCP）的完整描述，用户审批时复核。可为空。 */
  description?: string;
}

const OPTIONS: Array<{ key: string; label: string; decision: ApprovalDecision }> = [
  { key: "a", label: "Approve (允许本次)", decision: "approved" },
  { key: "r", label: "Reject (拒绝)", decision: "rejected" },
  { key: "l", label: "Approve all (full_auto / 本会话全部放行)", decision: "always_allow_level" },
];

const RISK_COLOR: Record<string, string> = {
  READ: C.green,
  WRITE: C.yellow,
  DANGER: C.accent,
};

/** 独立组件的描述限高。嵌在 App 里时不能用它：Todo、进度和状态栏还要占行。 */
export function descViewportLines(termRows: number): number {
  const rows = termRows > 0 ? termRows : 24;
  return Math.min(10, Math.max(4, rows - 16));
}

/** App 扣掉标题、进度、Todo、队列和状态栏之后，对话框最多能占的行数。 */
export function approvalMaxHeight(input: {
  termRows: number;
  headerRows: number;
  progressRows: number;
  todoRows: number;
  followupRows: number;
  statusRows: number;
}): number {
  const rows = input.termRows > 0 ? input.termRows : 24;
  const reserved =
    Math.max(0, input.headerRows) +
    Math.max(0, input.progressRows) +
    Math.max(0, input.todoRows) +
    Math.max(0, input.followupRows) +
    Math.max(0, input.statusRows);
  return Math.max(1, rows - reserved);
}

/**
 * 展开后工具、参数和描述共用一个滚动正文，审批按钮固定在下面。
 * 参数换行再长也不占掉正文：预算够就留出完整按钮；不够就收成一行快捷键，正文至少 1 行。
 */
export function approvalScrollLayout(budgetRows: number): { bodyRows: number; compact: boolean } {
  const budget = Number.isFinite(budgetRows) ? Math.max(1, Math.trunc(budgetRows)) : 1;
  // 边框 2 + 标题 1 + 标题分隔 1 + 行号 1 + 分隔 1 + 三个选项 3 + 提示 1。
  const fullChrome = 10;
  if (budget - fullChrome >= 1) {
    return { bodyRows: budget - fullChrome, compact: false };
  }
  // 放不下标题分隔和三行按钮时：边框 2 + 标题 1 + 一行按钮。按钮不再画进正文。
  const compactChrome = 4;
  return { bodyRows: Math.max(1, budget - compactChrome), compact: true };
}

export function clampDescScroll(offset: number, lineCount: number, viewport: number): number {
  const max = Math.max(0, lineCount - Math.max(1, viewport));
  if (!Number.isFinite(offset)) return 0;
  return Math.min(max, Math.max(0, Math.trunc(offset)));
}

/** 与 Bun/OpenTUI 运行时同一套显示宽度。手写区间表会把 🤖 算成 1 格、把 ZWJ 字素簇拆开。 */
export function displayCellWidth(text: string): number {
  return Bun.stringWidth(text);
}

function graphemeSegments(text: string): string[] {
  if (typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    return Array.from(segmenter.segment(text), (part) => part.segment);
  }
  return Array.from(text);
}

/** 按字素簇和运行时宽度软换行。调用侧传入的宽度应是扣掉边框、缩进和滚动条后的可见格数。 */
export function wrapDescriptionLines(description: string, width: number): string[] {
  const limit = Math.max(16, width);
  const out: string[] = [];
  for (const raw of description.split("\n")) {
    if (displayCellWidth(raw) <= limit) {
      out.push(raw);
      continue;
    }
    let current = "";
    let currentWidth = 0;
    for (const segment of graphemeSegments(raw)) {
      const segmentWidth = displayCellWidth(segment);
      if (current && currentWidth + segmentWidth > limit) {
        out.push(current);
        current = "";
        currentWidth = 0;
      }
      current += segment;
      currentWidth += segmentWidth;
    }
    if (current.length > 0) out.push(current);
  }
  return out;
}

export function ApprovalDialog({
  approval,
  onDecision,
  maxHeight,
}: {
  approval: ApprovalInfo;
  onDecision: (decision: ApprovalDecision) => void;
  /** App 给出的剩余行数。不传时按整终端估算，独立组件测试保持原视口。 */
  maxHeight?: number;
}) {
  const [idx, setIdx] = useState(0);
  // 2026-10-12 K3-3：外部工具 description 不再只看 120 字符截断——
  // 投毒文本往往藏在中后段；按 v 展开/收起。
  // 2026-10-12 P2：展开态进限高 ScrollBox（↑↓/PgUp/PgDn 滚动），审批选项
  // 固定在滚动区外——3291+ 字符展开不再把批准/拒绝挤出屏幕。
  const [expanded, setExpanded] = useState(false);
  const [descScroll, setDescScroll] = useState(0);
  const { height: termRows, width: termCols } = useTerminalDimensions();
  const scrollAccel = useMemo(() => createScrollAcceleration(), []);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const riskColor = RISK_COLOR[approval.risk] || C.yellow;
  const argsPreview =
    approval.args.length > 200 ? `${approval.args.slice(0, 200)}...` : approval.args;
  const description = approval.description ?? "";
  const descPreview =
    description.length > 120 ? `${description.slice(0, 120)}...` : description;
  const wrapWidth = (termCols || 80) - 16;
  const descLines = useMemo(
    // 预算 = 终端宽 − 边框2 − padding2 − "  "缩进2 − 滚动条1 − 余量3。
    // 超宽行会被横截、滚动也到不了尾，所以收紧到 -16。
    () => wrapDescriptionLines(description, wrapWidth),
    [description, wrapWidth],
  );
  const standaloneViewport = descViewportLines(termRows || 24);
  const scrollLayout = maxHeight == null ? null : approvalScrollLayout(maxHeight);
  const sharedBody = expanded && scrollLayout != null;
  const bodyLines = useMemo(() => {
    const tool = wrapDescriptionLines(`Tool: ${approval.tool}`, wrapWidth);
    const args = wrapDescriptionLines(`Args: ${argsPreview}`, wrapWidth);
    return description ? [...tool, ...args, ...descLines] : [...tool, ...args];
  }, [approval.tool, argsPreview, description, descLines, wrapWidth]);
  const descViewport = sharedBody ? scrollLayout.bodyRows : standaloneViewport;
  const scrollLines = sharedBody ? bodyLines : descLines;
  // 键盘闭包读最新值，避免截到挂载时的空数组（同 DialogDoc 的 pattern）。
  const descLinesRef = useRef(scrollLines);
  const descViewportRef = useRef(descViewport);
  descLinesRef.current = scrollLines;
  descViewportRef.current = descViewport;

  const viewportRows = () => {
    const planned = Math.max(1, descViewportRef.current);
    const measured = scrollRef.current?.viewport?.height ?? 0;
    // 缩窗后测量高度可能还是旧的更大值。用它去夹偏移会把已经到文末的位置算小，行号就停在旧窗口。
    if (measured > 0 && measured <= planned) return measured;
    return planned;
  };

  // 位置只认 scrollbox.scrollTop。滚轮和滚动条改的是它，键盘再按自己的偏移会跳回顶部。
  const readScrollTop = () => {
    const box = scrollRef.current;
    return clampDescScroll(
      box ? box.scrollTop : descScroll,
      descLinesRef.current.length,
      viewportRows(),
    );
  };

  const atEndRef = useRef(false);
  const keepEndRef = useRef(false);
  const ignoreScrollEchoRef = useRef(false);
  const publishScroll = (clamped: number) => {
    const view = Math.max(1, descViewportRef.current);
    const max = Math.max(0, descLinesRef.current.length - view);
    const atEnd = descLinesRef.current.length > view && clamped >= max;
    if (atEnd) {
      atEndRef.current = true;
      keepEndRef.current = false;
    } else if (!keepEndRef.current) {
      atEndRef.current = false;
    }
    setDescScroll((prev) => (prev === clamped ? prev : clamped));
  };
  const pinEnd = () => {
    if (!atEndRef.current) return false;
    const box = scrollRef.current;
    const planned = Math.max(1, descViewportRef.current);
    const measured = box?.viewport?.height || 0;
    // 样式已经变矮，但 scrollbox 还没重排时，先别用旧高度把“已到文末”清掉。
    if (measured > planned) return false;
    const view = measured > 0 ? measured : planned;
    const max = Math.max(0, descLinesRef.current.length - view);
    keepEndRef.current = true;
    ignoreScrollEchoRef.current = true;
    if (box && box.scrollTop !== max) box.scrollTop = max;
    ignoreScrollEchoRef.current = false;
    const applied = box ? box.scrollTop : max;
    if (applied >= max) {
      keepEndRef.current = false;
      atEndRef.current = descLinesRef.current.length > view;
      publishScroll(applied);
      return true;
    }
    return false;
  };
  const schedulePinEnd = () => {
    let tries = 0;
    const tick = () => {
      if (!atEndRef.current) return;
      if (pinEnd()) return;
      if (tries >= 12) return;
      tries += 1;
      setTimeout(tick, 0);
    };
    setTimeout(tick, 0);
  };

  const applyDescScroll = (next: number) => {
    const clamped = clampDescScroll(next, descLinesRef.current.length, viewportRows());
    const box = scrollRef.current;
    if (box && box.scrollTop !== clamped) box.scrollTop = clamped;
    const live = box
      ? clampDescScroll(box.scrollTop, descLinesRef.current.length, viewportRows())
      : clamped;
    publishScroll(live);
  };

  const syncFromNative = () => {
    if (ignoreScrollEchoRef.current) return;
    const box = scrollRef.current;
    const raw = box ? box.scrollTop : descScroll;
    const clamped = clampDescScroll(raw, descLinesRef.current.length, viewportRows());
    // 旧视口把新的文末偏移夹小之后，不要把这个更小的数写进行号。
    if (atEndRef.current && raw > clamped) return;
    publishScroll(clamped);
  };

  useEffect(() => {
    if (!expanded) return;
    const box = scrollRef.current;
    if (!box) return;
    const onChange = () => syncFromNative();
    const viewport = box.viewport as { onSizeChange?: (() => void) | undefined };
    const previousSize = viewport.onSizeChange;
    viewport.onSizeChange = () => {
      previousSize?.();
      pinEnd();
    };
    box.verticalScrollBar.on("change", onChange);
    pinEnd();
    return () => {
      box.verticalScrollBar.off("change", onChange);
      if (viewport.onSizeChange !== previousSize) viewport.onSizeChange = previousSize;
    };
  }, [expanded, scrollLines.length, descViewport]);

  useOnResize(() => {
    if (!expanded) return;
    if (atEndRef.current) {
      schedulePinEnd();
      return;
    }
    const box = scrollRef.current;
    if (!box) return;
    const live = clampDescScroll(box.scrollTop, descLinesRef.current.length, viewportRows());
    if (box.scrollTop !== live) box.scrollTop = live;
    publishScroll(live);
  });

  useKeyboard((key) => {
    if (key.name === "return") {
      onDecision(OPTIONS[idx].decision);
      return;
    }
    const lower = (key.name || "").toLowerCase();
    if (lower === "v" && description.length > 120) {
      setExpanded((value) => {
        if (value) applyDescScroll(0); // 收起时复位到顶部
        return !value;
      });
      return;
    }
    if (expanded) {
      // 展开态：↑↓ 在原生 scrollTop 上增减；a/r/l + ↵ 仍然可用（审批不能滚丢）。
      const step = Math.max(1, viewportRows() - 1);
      const current = readScrollTop();
      if (key.name === "pageup" || key.name === "home") {
        applyDescScroll(key.name === "home" ? 0 : current - step);
        return;
      }
      if (key.name === "pagedown" || key.name === "end") {
        applyDescScroll(key.name === "end" ? descLinesRef.current.length : current + step);
        return;
      }
      if (key.name === "up") {
        applyDescScroll(current - 1);
        return;
      }
      if (key.name === "down") {
        applyDescScroll(current + 1);
        return;
      }
    } else {
      if (key.name === "up") {
        setIdx((i) => Math.max(0, i - 1));
        return;
      }
      if (key.name === "down") {
        setIdx((i) => Math.min(OPTIONS.length - 1, i + 1));
        return;
      }
    }
    const hit = OPTIONS.find((o) => o.key === lower);
    if (hit) onDecision(hit.decision);
  });

  const visibleRows = Math.max(descViewport, 1);
  const nativeTop = scrollRef.current?.scrollTop;
  const fromNative = clampDescScroll(
    nativeTop == null ? descScroll : nativeTop,
    scrollLines.length,
    visibleRows,
  );
  const endTop = Math.max(0, scrollLines.length - visibleRows);
  const safeDescScroll = atEndRef.current ? Math.max(fromNative, endTop) : fromNative;
  const descSliceStart = scrollLines.length === 0 ? 0 : safeDescScroll + 1;
  const descSliceEnd = Math.min(safeDescScroll + visibleRows, scrollLines.length);
  const capped = expanded && maxHeight != null;
  const compactFooter = sharedBody && scrollLayout.compact;

  return (
    <box
      style={{
        flexShrink: 0,
        border: true,
        borderColor: riskColor,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.panel,
        ...(capped ? { height: maxHeight, maxHeight, overflow: "hidden" as const } : {}),
      }}
    >
      <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.panel }}>
        <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
          <text fg={riskColor} attributes={1}>
            {"  Safety Approval"}
          </text>
          <box style={{ flexGrow: 1 }} />
          <text fg={riskColor} attributes={1}>
            {approval.risk}
            {" "}
          </text>
        </box>
        {compactFooter ? null : (
          <text fg={C.overlay2}>{"─".repeat(40)}</text>
        )}
        {sharedBody ? null : (
          <text fg={C.subtext}>
            {"  Tool: "}
            <span fg={C.text} attributes={1}>
              {approval.tool}
            </span>
          </text>
        )}
        {sharedBody ? null : <text fg={C.overlay2}>{`  Args: ${argsPreview}`}</text>}
        {description && !expanded ? (
          <text fg={C.overlay2}>
            {`  Desc: ${descPreview}${description.length > 120 ? " (按 v 展开全文)" : ""}`}
          </text>
        ) : null}
        {description && expanded && !sharedBody ? (
          <box style={{ flexDirection: "column", width: "100%" }}>
            <text fg={C.overlay2}>{`  Desc（全文 ${descLines.length} 行，↑↓/PgUp/PgDn 滚动，v 收起）:`}</text>
            <scrollbox
              ref={scrollRef}
              stickyScroll={false}
              stickyStart="top"
              scrollAcceleration={scrollAccel}
              style={{
                rootOptions: {
                  flexShrink: 0,
                  height: visibleRows,
                  maxHeight: visibleRows,
                  border: false,
                  backgroundColor: C.panel,
                },
                viewportOptions: { flexGrow: 1, backgroundColor: C.panel },
                contentOptions: { backgroundColor: C.panel },
                verticalScrollbarOptions: {
                  showArrows: false,
                  trackOptions: {
                    foregroundColor: SCROLLBAR_TRACK.foregroundColor,
                    backgroundColor: SCROLLBAR_TRACK.backgroundColor,
                  },
                },
              }}
            >
              {descLines.map((line, i) => (
                <box key={i} style={{ width: "100%", height: 1, flexShrink: 0 }}>
                  <text fg={C.overlay2} selectable>
                    {`  ${line}`}
                  </text>
                </box>
              ))}
            </scrollbox>
            <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
              <box style={{ flexGrow: 1, height: 1 }} />
              <text fg={C.overlay2}>{` ${descSliceStart}-${descSliceEnd}/${descLines.length} `}</text>
            </box>
          </box>
        ) : null}
        {sharedBody ? (
          <box style={{ flexDirection: "column", width: "100%" }}>
            <scrollbox
              ref={scrollRef}
              stickyScroll={false}
              stickyStart="top"
              scrollAcceleration={scrollAccel}
              style={{
                rootOptions: {
                  flexShrink: 0,
                  height: visibleRows,
                  maxHeight: visibleRows,
                  border: false,
                  backgroundColor: C.panel,
                },
                viewportOptions: { flexGrow: 1, backgroundColor: C.panel },
                contentOptions: { backgroundColor: C.panel },
                verticalScrollbarOptions: {
                  showArrows: false,
                  trackOptions: {
                    foregroundColor: SCROLLBAR_TRACK.foregroundColor,
                    backgroundColor: SCROLLBAR_TRACK.backgroundColor,
                  },
                },
              }}
            >
              {scrollLines.map((line, i) => (
                <box key={i} style={{ width: "100%", height: 1, flexShrink: 0 }}>
                  <text fg={C.overlay2} selectable>
                    {`  ${line}`}
                  </text>
                </box>
              ))}
            </scrollbox>
            {compactFooter ? null : (
              <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
                <box style={{ flexGrow: 1, height: 1 }} />
                <text fg={C.overlay2}>{` ${descSliceStart}-${descSliceEnd}/${scrollLines.length} `}</text>
              </box>
            )}
          </box>
        ) : null}
        {compactFooter ? (
          <box style={{ width: "100%", height: 1, flexShrink: 0, overflow: "hidden", flexDirection: "row" }}>
            {OPTIONS.map((o) => (
              <box key={o.key} onMouseDown={() => onDecision(o.decision)}>
                <text fg={riskColor}>{` [${o.key}]${o.decision === "approved" ? "允许" : o.decision === "rejected" ? "拒绝" : "全部"}`}</text>
              </box>
            ))}
          </box>
        ) : (
          <>
        <text fg={C.overlay2}>{"─".repeat(40)}</text>
        {OPTIONS.map((o, i) => {
          const sel = i === idx;
          return (
            <box
              key={o.key}
              style={{ width: "100%", backgroundColor: sel ? C.surface1 : C.bg }}
              onMouseDown={() => onDecision(o.decision)}
            >
              <text fg={sel ? riskColor : C.subtext}>
                {sel ? " ❯ " : "   "}
                {`[${o.key}] ${o.label}`}
              </text>
            </box>
          );
        })}
        <text fg={C.overlay2}>
          {description.length > 120
            ? expanded
              ? "  ↑↓/PgUp/PgDn 滚动 Desc   ↵ 确认   a/r/l 快捷   v 收起"
              : "  ↑↓ 选择   ↵ 确认   a/r/l 快捷   v 展开/收起 Desc   鼠标点击"
            : "  ↑↓ 选择   ↵ 确认   a/r/l 快捷   鼠标点击"}
        </text>
          </>
        )}
      </box>
    </box>
  );
}
