import type { Mode } from "./types.ts";
import { MODE_LABELS } from "./types.ts";
import { C } from "./theme.ts";

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
}

export type StatusSegment = { key: string; text: string; fg: string; bold?: boolean };

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
    { key: "shortcuts", text: "Tab:切换 /:命令 Ctrl+T:思考 Ctrl+P:设置", fg: C.overlay2 },
  ];

  const order = all.map((s) => s.key);
  const optional = ["context", "cache", "cancel", "shortcuts"];
  const visible = new Set(["connection", "mode", "thinking"]);
  const contentWidth = Math.max(1, input.width - 2);

  for (const key of optional) {
    const candidate = order.filter((k) => visible.has(k) || k === key);
    const joined = candidate
      .map((k) => all.find((s) => s.key === k)!.text)
      .join(" │ ");
    if (joined.length <= contentWidth) visible.add(key);
  }

  return order.filter((k) => visible.has(k)).map((k) => all.find((s) => s.key === k)!);
}

/** Flat text for tests / narrow fallbacks. */
export function formatStatusBarText(input: StatusBarInput): string {
  return buildStatusSegments(input)
    .map((s) => s.text)
    .join(" │ ");
}
