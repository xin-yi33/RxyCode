import { useMemo, useRef, useState } from "react";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
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

/** 展开描述的限高（行数）：给标题/选项/底栏留出位置，80×24 也能留 8 行。 */
export function descViewportLines(termRows: number): number {
  const rows = termRows > 0 ? termRows : 24;
  return Math.min(10, Math.max(4, rows - 16));
}

export function clampDescScroll(offset: number, lineCount: number, viewport: number): number {
  const max = Math.max(0, lineCount - Math.max(1, viewport));
  if (!Number.isFinite(offset)) return 0;
  return Math.min(max, Math.max(0, Math.trunc(offset)));
}

// 宽字符按 2 终端格计（CJK/全角）；一行 64 个汉字实际是 128 格——
// 这就是 P2 复现里 TAILMARK 永远滚不到的根因（按 JS length 换行超宽被横截）。
// wcwidth 常见 East-Asian Wide/Fullwidth 区段（含补充平面）——一行 64 个汉字
// 实际是 128 格，这就是 P2 复现里 TAILMARK 永远滚不到、被横向截掉的根因。
const _WIDE_RANGES: Array<[number, number]> = [
  [0x1100, 0x115f], // Hangul Jamo
  [0x2e80, 0x303e], // CJK 部首/康熙部首/描述符
  [0x3041, 0x33ff], // 假名/CJK 兼容
  [0x3400, 0x4dbf], // CJK 扩展 A
  [0x4e00, 0x9fff], // CJK 统一表意
  [0xa000, 0xa4cf], // 彝文
  [0xa960, 0xa97f], // Hangul Jamo 扩展 A
  [0xac00, 0xd7a3], // Hangul 音节
  [0xf900, 0xfaff], // CJK 兼容表意
  [0xfe10, 0xfe19], // 竖排标点
  [0xfe30, 0xfe6b], // CJK 兼容形式/小形式
  [0xff00, 0xff60], // 全角形式
  [0xffe0, 0xffe6], // 全角符号
  [0x1f300, 0x1f64f], // emoji
  [0x20000, 0x3fffd], // CJK 扩展 B+
];

function charCellWidth(codePoint: number): number {
  for (const [lo, hi] of _WIDE_RANGES) {
    if (codePoint >= lo && codePoint <= hi) return 2;
  }
  return 1;
}

export function displayCellWidth(text: string): number {
  let width = 0;
  for (const char of text) width += charCellWidth(char.codePointAt(0) ?? 0);
  return width;
}

/** 把长段描述按显示宽度软换行成安全行：超宽行在限高滚动区里会被横向截掉，
 *  滚动也到不了尾部（P2 复审复现形态）。调用侧传入的宽度应为扣掉
 *  边框/padding/缩进/滚动条后的可见格数。 */
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
    for (const char of raw) {
      const charWidth = charCellWidth(char.codePointAt(0) ?? 0);
      if (currentWidth + charWidth > limit) {
        out.push(current);
        current = "";
        currentWidth = 0;
      }
      current += char;
      currentWidth += charWidth;
    }
    if (current.length > 0) out.push(current);
  }
  return out;
}

export function ApprovalDialog({
  approval,
  onDecision,
}: {
  approval: ApprovalInfo;
  onDecision: (decision: ApprovalDecision) => void;
}) {
  const [idx, setIdx] = useState(0);
  // 2026-10-12 K3-3：外部工具 description 不再只看 120 字符截断——
  // 投毒文本往往藏在中后段；按 v 展开/收起。
  // 2026-10-12 P2：展开态进限高 ScrollBox（↑↓/PgUp/PgDn 滚动），审批选项
  // 固定在滚动区外——3291+ 字符展开不再把批准/拒绝挤出屏幕。
  const [expanded, setExpanded] = useState(false);
  const [descScroll, setDescScroll] = useState(0);
  const { height: termRows, width: termCols } = useTerminalDimensions();
  const descViewport = descViewportLines(termRows || 24);
  const scrollAccel = useMemo(() => createScrollAcceleration(), []);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const riskColor = RISK_COLOR[approval.risk] || C.yellow;
  const argsPreview =
    approval.args.length > 200 ? `${approval.args.slice(0, 200)}...` : approval.args;
  const description = approval.description ?? "";
  const descPreview =
    description.length > 120 ? `${description.slice(0, 120)}...` : description;
  const descLines = useMemo(
    // 预算 = 终端宽 − 边框2 − padding2 − "  "缩进2 − 滚动条1 − 余量3。
    // 超宽行会被横截、滚动也到不了尾（P2 复现），所以收紧到 -16。
    () => wrapDescriptionLines(description, (termCols || 80) - 16),
    [description, termCols],
  );
  // 键盘闭包读最新值，避免截到挂载时的空数组（同 DialogDoc 的 pattern）。
  const descLinesRef = useRef(descLines);
  const descViewportRef = useRef(descViewport);
  const descOffsetRef = useRef(0);
  descLinesRef.current = descLines;
  descViewportRef.current = descViewport;

  const applyDescScroll = (next: number) => {
    const clamped = clampDescScroll(
      next,
      descLinesRef.current.length,
      descViewportRef.current,
    );
    descOffsetRef.current = clamped;
    setDescScroll(clamped);
    try {
      const box = scrollRef.current;
      if (box) box.scrollTop = clamped;
    } catch {
      // ignore
    }
  };

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
      // 展开态：↑↓ 交给描述滚动区；a/r/l + ↵ 仍然可用（审批不能滚丢）。
      if (key.name === "pageup" || key.name === "home") {
        applyDescScroll(
          key.name === "home" ? 0 : descOffsetRef.current - Math.max(1, descViewportRef.current - 1),
        );
        return;
      }
      if (key.name === "pagedown" || key.name === "end") {
        applyDescScroll(
          key.name === "end"
            ? descLinesRef.current.length
            : descOffsetRef.current + Math.max(1, descViewportRef.current - 1),
        );
        return;
      }
      if (key.name === "up") {
        applyDescScroll(descOffsetRef.current - 1);
        return;
      }
      if (key.name === "down") {
        applyDescScroll(descOffsetRef.current + 1);
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

  const safeDescScroll = clampDescScroll(descScroll, descLines.length, descViewport);
  const descSliceStart = safeDescScroll + 1;
  const descSliceEnd = Math.min(safeDescScroll + descViewport, descLines.length);

  return (
    <box
      style={{
        flexShrink: 0,
        border: true,
        borderColor: riskColor,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
        <box style={{ flexDirection: "row", width: "100%" }}>
          <text fg={riskColor} attributes={1}>
            {"  Safety Approval"}
          </text>
          <box style={{ flexGrow: 1 }} />
          <text fg={riskColor} attributes={1}>
            {approval.risk}
            {" "}
          </text>
        </box>
        <text fg={C.overlay2}>{"─".repeat(40)}</text>
        <text fg={C.subtext}>
          {"  Tool: "}
          <span fg={C.text} attributes={1}>
            {approval.tool}
          </span>
        </text>
        <text fg={C.overlay2}>{`  Args: ${argsPreview}`}</text>
        {description && !expanded ? (
          <text fg={C.overlay2}>
            {`  Desc: ${descPreview}${description.length > 120 ? " (按 v 展开全文)" : ""}`}
          </text>
        ) : null}
        {description && expanded ? (
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
                  height: descViewport,
                  maxHeight: descViewport,
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
      </box>
    </box>
  );
}
