import type { Mode } from "./types.ts";
import { MODE_LABELS } from "./types.ts";
import { C } from "./theme.ts";
import { stringWidth } from "./layout.ts";

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

// 2026-10-09 修复：快捷键段被整段剪没时 Ctrl+P和法律其余提示完全不可见
// （终端 <126 列实测）——先试全文，放不下退紧凑文案，再放不下才剪。
// 紧凑版必须保留 Ctrl+P（设置/命令面板入口）与 Ctrl+T:Todo。
const SHORTCUTS_FULL = "Tab:切换 /:命令 Ctrl+E:思考 Ctrl+T:Todo Ctrl+P:设置";
const SHORTCUTS_COMPACT = "Tab切换 /命令 Ctrl+P设置 Ctrl+T:Todo";

/** Classic Ink StatusBar segments (multi-color). */
export function buildStatusSegments(input: StatusBarInput): StatusSegment[] {
  const connIcon = input.connected ? "●" : "○";
  const connLabel = input.connected ? "online" : "offline";
  const ctxUsed = input.contextUsedK.toFixed(1);
  const ctxMax = String(input.contextMaxK);

  const all: StatusSegment[] = [
    {
      key: "connection",
      text: `${connIcon} ${connLabel}`,
      fg: input.connected ? C.green : C.accent,
      bold: true,
    },
    { key: "context", text: `上下文:${ctxUsed}k/${ctxMax}k`, fg: C.primary },
    { key: "cache", text: `缓存:${input.cacheSize}/${input.cacheRate}`, fg: C.teal },
    { key: "mode", text: MODE_LABELS[input.mode], fg: input.modeColor, bold: true },
    {
      key: "thinking",
      text: `思考:${input.thinkingExpanded ? "开" : "关"}`,
      fg: input.thinkingExpanded ? C.green : C.overlay2,
    },
    { key: "cancel", text: "Esc:终止", fg: C.overlay2 },
    { key: "shortcuts", text: "Tab:切换 /:命令 Ctrl+E:思考 Ctrl+T:Todo Ctrl+P:设置", fg: C.overlay2 },
  ];
  if (input.teamRole) {
    all.splice(4, 0, { key: "teamRole", text: `[${input.teamRole}]`, fg: C.yellow, bold: true });
  }
  if (input.teamBudget) {
    all.splice(input.teamRole ? 5 : 4, 0, {
      key: "teamBudget",
      text: input.teamBudget,
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
