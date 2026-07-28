/** Classic RxyCode WORDMARK — R X Y C O D E (same as Ink logo.ts). */
export const WORDMARK = [
  "███████  ██   ██  ██   ██   █████    █████   ██████    █████ ",
  "██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██",
  "██   ██   ██ ██   ██   ██  ██       ██   ██  ██   ██  ███████",
  "███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██",
  "██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ",
  "██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██",
  "██   ██  ██   ██    ███     █████    █████   ██████    █████ ",
] as const;

export const WORDMARK_DISPLAY_WIDTH = 61;

export function centerPad(line: string, cols: number): string {
  const trimmed = line.replace(/ +$/, "");
  const w = trimmed.length;
  if (cols <= w) return trimmed;
  const pad = Math.max(0, Math.floor((cols - w) / 2));
  return " ".repeat(pad) + trimmed;
}

export const WELCOME_LINES: Array<{ text: string; fg: string; bold?: boolean }> = [
  { text: "  你好！我是 RxyCode，可以帮你分析、规划并执行各类任务", fg: "#FFB6C1" },
  { text: "  · 代码开发 - 编写、调试、重构代码", fg: "#FF69B4" },
  { text: "  · 文件操作 - 读写、检索、编辑文件", fg: "#FF69B4" },
  { text: "  · 项目管理 - Git、测试运行、依赖管理", fg: "#FF69B4" },
  { text: "  · 问题排查 - 分析错误、定位 bug、修复方案", fg: "#FF69B4" },
  { text: "  · 研究分析 - 检索来源、比较方案、整理结论", fg: "#FF69B4" },
  { text: "  · 通用任务 - 信息整理、计划执行、多步协作", fg: "#FF69B4" },
  { text: "  有什么我可以帮你的？", fg: "#888888" },
  { text: "  快捷键: Ctrl+P 命令面板 · Ctrl+T 思考展开 · Tab 切换模式 · Esc 终止", fg: "#555555" },
];
