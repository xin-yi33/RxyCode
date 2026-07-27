import { MODE_LABELS, type Mode } from "./types.ts";

export interface StatusBarInput {
  connected: boolean;
  contextUsedK: number;
  contextMaxK: number;
  cacheSize: string;
  cacheRate: string;
  mode: Mode;
  thinkingExpanded: boolean;
  width: number;
}

type SegmentKey = "connection" | "context" | "cache" | "mode" | "thinking" | "cancel" | "shortcuts";

const SEGMENT_ORDER: SegmentKey[] = [
  "connection",
  "context",
  "cache",
  "mode",
  "thinking",
  "cancel",
  "shortcuts",
];

const OPTIONAL_PRIORITY: SegmentKey[] = ["context", "cache", "cancel", "shortcuts"];

export function formatStatusBarText(input: StatusBarInput): string {
  const connIcon = input.connected ? "●" : "○";
  const connLabel = input.connected ? "online" : "offline";
  const ctxUsed = input.contextUsedK.toFixed(1);
  const ctxMax = String(input.contextMaxK);

  const text: Record<SegmentKey, string> = {
    connection: `${connIcon} ${connLabel}`,
    context: `上下文:${ctxUsed}k/${ctxMax}k`,
    cache: `缓存:${input.cacheSize}/${input.cacheRate}`,
    mode: MODE_LABELS[input.mode],
    thinking: `思考:${input.thinkingExpanded ? "开" : "关"}`,
    cancel: "Esc:终止",
    shortcuts: "Tab:切换 /:命令 Ctrl+T:思考 Ctrl+P:设置",
  };

  const visible = new Set<SegmentKey>(["connection", "mode", "thinking"]);
  const contentWidth = Math.max(1, input.width - 2);
  for (const key of OPTIONAL_PRIORITY) {
    const candidate = SEGMENT_ORDER.filter((segment) => visible.has(segment) || segment === key);
    const joined = candidate.map((segment) => text[segment]).join(" │ ");
    if (joined.length <= contentWidth) {
      visible.add(key);
    }
  }

  return SEGMENT_ORDER.filter((key) => visible.has(key))
    .map((key) => text[key])
    .join(" │ ");
}
