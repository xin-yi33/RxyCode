import type { Mode } from "./types.ts";
import { MODE_LABELS } from "./types.ts";
import { C } from "./theme.ts";
import { stringWidth } from "./layout.ts";
import {
  formatBudgetPair,
  formatQuotaPair,
  rateCell,
  sizeCell,
} from "./lib/displayColumns.ts";

export interface StatusBarInput {
  connected: boolean;
  contextUsedK: number;
  contextMaxK: number;
  cacheSize: string;
  cacheRate: string;
  mode: Mode;
  thinkingExpanded: boolean;
  width: number;
  modeColor: string;
  teamRole?: string;
  teamBudget?: string;
}

export type StatusSegment = { key: string; text: string; fg: string; bold?: boolean };

// 2026-10-09 修复：快捷键段被整段剪没时 Ctrl+P 和法律其余提示完全不可见
// （终端 <126 列实测）——先试全文，放不下退紧凑文案，再放不下才剪。
// 紧凑版必须保留 Ctrl+P（设置/命令面板入口）与 Ctrl+T:思考（2026-10-11
// 键位换回：Ctrl+T=思考展开，Todo 移到 Ctrl+E）。
const SHORTCUTS_FULL = "Tab:切换 /:命令 Ctrl+T:思考 Ctrl+E:Todo Ctrl+P:设置";
const SHORTCUTS_COMPACT = "Tab切换 /命令 Ctrl+P设置 Ctrl+T:思考";

/**
 * Classic Ink StatusBar segments (multi-color).
 *
 * 2026-10-24 UI polish: numeric fields render in fixed DISPLAY-cell columns.
 * Quota/size/rate values change width while labels are CJK (2 cells each), so
 * plain JS-string padding would drift; the helpers pad by terminal cells and
 * keep each numeric column's right edge (and the "/" separator) anchored.
 */
export function buildStatusSegments(input: StatusBarInput): StatusSegment[] {
  const connIcon = input.connected ? "●" : "○";
  const connLabel = input.connected ? "online" : "offline";
  const contextText =
    "上下文:" +
    formatQuotaPair(input.contextUsedK.toFixed(1) + "k", String(input.contextMaxK) + "k");
  // Size / rate are numeric cells too ("0B" → "907.0k", "0.0%" → "100.0%").
  const cacheText = "缓存:" + sizeCell(input.cacheSize) + "/" + rateCell(input.cacheRate);

  const all: StatusSegment[] = [
    {
      key: "connection",
      text: connIcon + " " + connLabel,
      fg: input.connected ? C.green : C.accent,
      bold: true,
    },
    { key: "context", text: contextText, fg: C.primary },
    { key: "cache", text: cacheText, fg: C.teal },
    { key: "mode", text: MODE_LABELS[input.mode], fg: input.modeColor, bold: true },
    {
      key: "thinking",
      text: "思考:" + (input.thinkingExpanded ? "开" : "关"),
      fg: input.thinkingExpanded ? C.green : C.overlay2,
    },
    { key: "cancel", text: "Esc:终止", fg: C.overlay2 },
    { key: "shortcuts", text: SHORTCUTS_FULL, fg: C.overlay2 },
  ];
  if (input.teamRole) {
    all.splice(4, 0, { key: "teamRole", text: "[" + input.teamRole + "]", fg: C.yellow, bold: true });
  }
  if (input.teamBudget) {
    // Budget is a used/max quota too — align both sides so the slash is stable.
    all.splice(input.teamRole ? 5 : 4, 0, {
      key: "teamBudget",
      text: formatBudgetPair(input.teamBudget),
      fg: C.teal,
    });
  }

  const order = all.map((s) => s.key);
  const optional = ["context", "cache", "cancel", "shortcuts"];
  const visible = new Set(["connection", "mode", "thinking"]);
  if (input.teamRole) visible.add("teamRole");
  if (input.teamBudget) visible.add("teamBudget");
  const contentWidth = Math.max(1, input.width - 2);

  for (const key of optional) {
    const texts =
      key === "shortcuts"
        ? [SHORTCUTS_FULL, SHORTCUTS_COMPACT]
        : [all.find((s) => s.key === key)!.text];
    for (const text of texts) {
      const candidate = order.filter((k) => visible.has(k) || k === key);
      const joined = candidate
        .map((k) => (k === key ? text : all.find((s) => s.key === k)!.text))
        .join(" │ ");
      // CJK status labels are 2 columns; JS string.length would overflow the row.
      if (stringWidth(joined) <= contentWidth) {
        visible.add(key);
        all.find((s) => s.key === key)!.text = text;
        break;
      }
    }
  }

  return order.filter((k) => visible.has(k)).map((k) => all.find((s) => s.key === k)!);
}

/** Flat text for tests / narrow fallbacks. */
export function formatStatusBarText(input: StatusBarInput): string {
  return buildStatusSegments(input)
    .map((s) => s.text)
    .join(" │ ");
}
