import { NO_MODEL_WELCOME_HINT } from "./modelSetup.ts";

/**
 * Classic RxyCode branding — colors frozen to original Ink screenshot:
 *   LightPink #FFB6C1  ·  HotPink #FF69B4
 * Logo: Unicode WORDMARK (same geometry as Ink Banner), not shade ascii-font.
 */

export const WORDMARK = [
  "███████  ██   ██  ██   ██   █████    █████   ██████    █████ ",
  "██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██",
  "██   ██   ██ ██   ██   ██  ██       ██   ██  ██   ██  ███████",
  "███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██",
  "██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ",
  "██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██",
  "██   ██  ██   ██    ███     █████    █████   ██████    █████ ",
] as const;

export const WORDMARK_UNICODE = WORDMARK;

/** Original Ink light pink (header / greeting / logo top / accents). */
export const LOGO_INK_TOP = "#FFB6C1";
/** Original Ink hot pink (capabilities / build / logo body). */
export const LOGO_INK_BODY = "#FF69B4";
export const LOGO_FIELD_BG = "#000000";

export const BRAND_LIGHT = LOGO_INK_TOP;
export const BRAND_HOT = LOGO_INK_BODY;
/** @deprecated aliases — prefer BRAND_LIGHT / BRAND_HOT */
export const BRAND_PINK = BRAND_HOT;
export const BRAND_GREETING = BRAND_LIGHT;
export const BRAND_ACCENT = BRAND_HOT;
export const BRAND_MUTED = "#555555";

export function logoInkForRow(rowIndex: number): string {
  return rowIndex === 0 ? LOGO_INK_TOP : LOGO_INK_BODY;
}

export function getWordmark(): readonly string[] {
  return WORDMARK;
}

export const WORDMARK_DISPLAY_WIDTH = 61;

export function centerPad(line: string, cols: number): string {
  const trimmed = line.replace(/ +$/, "");
  const w = trimmed.length;
  if (cols <= w) return trimmed;
  const pad = Math.max(0, Math.floor((cols - w) / 2));
  return " ".repeat(pad) + trimmed;
}

export type WelcomePart = { text: string; fg: string; bold?: boolean };
export type WelcomeRow = { parts: WelcomePart[] };

/** Classic Ink ChatPanel welcome — exact split colors from original. */
export const WELCOME_ROWS: WelcomeRow[] = [
  { parts: [{ text: "  你好！我是 RxyCode，可以帮你分析、规划并执行各类任务", fg: "#FFB6C1" }] },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "代码开发", fg: "#FF69B4", bold: true },
      { text: " - 编写、调试、重构代码", fg: "#aaaaaa" },
    ],
  },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "文件操作", fg: "#FF69B4", bold: true },
      { text: " - 读写、检索、编辑文件", fg: "#aaaaaa" },
    ],
  },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "项目管理", fg: "#FF69B4", bold: true },
      { text: " - Git、测试运行、依赖管理", fg: "#aaaaaa" },
    ],
  },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "问题排查", fg: "#FF69B4", bold: true },
      { text: " - 分析错误、定位 bug、修复方案", fg: "#aaaaaa" },
    ],
  },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "研究分析", fg: "#FF69B4", bold: true },
      { text: " - 检索来源、比较方案、整理结论", fg: "#aaaaaa" },
    ],
  },
  {
    parts: [
      { text: "  · ", fg: "#666666" },
      { text: "通用任务", fg: "#FF69B4", bold: true },
      { text: " - 信息整理、计划执行、多步协作", fg: "#aaaaaa" },
    ],
  },
  { parts: [{ text: "  有什么我可以帮你的？", fg: "#888888" }] },
];

export function welcomeRowsForSetup(needsSetup: boolean): WelcomeRow[] {
  if (!needsSetup) return [...WELCOME_ROWS];
  return [
    ...WELCOME_ROWS,
    {
      parts: [{ text: `  ${NO_MODEL_WELCOME_HINT}`, fg: "#FFB6C1", bold: true }],
    },
  ];
}

export const SHORTCUTS_HINT =
  "  快捷键: Ctrl+P 命令面板 · Ctrl+T 思考展开 · Tab 切换模式 · Esc 终止";

export const WELCOME_LINES = WELCOME_ROWS.map((row) => ({
  text: row.parts.map((p) => p.text).join(""),
  fg: row.parts[0]?.fg ?? "#FF69B4",
}));
