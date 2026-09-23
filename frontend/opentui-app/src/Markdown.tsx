/**
 * Chat markdown uses OpenTUI MarkdownRenderable — same path as OpenCode
 * (`<markdown tableOptions={{ style: "grid" }}>`).
 * parseBlocks / formatBoxedTable stay for detection and grid-shape tests.
 */
import { SyntaxStyle } from "@opentui/core";
import { C } from "./theme.ts";

type Align = "left" | "center" | "right";

type Block =
  | { type: "heading"; level: number; content: string }
  | { type: "paragraph"; content: string }
  | { type: "code"; lang: string; content: string }
  | { type: "list"; ordered: boolean; items: { depth: number; content: string; checked?: boolean }[] }
  | { type: "blockquote"; lines: string[] }
  | { type: "table"; headers: string[]; aligns: Align[]; rows: string[][] }
  | { type: "hr" };

function displayWidth(s: string): number {
  let w = 0;
  for (const ch of s) {
    const code = ch.codePointAt(0) ?? 0;
    w += code > 0xff ? 2 : 1;
  }
  return w;
}

function isTableStart(lines: string[], i: number): boolean {
  const line = lines[i] ?? "";
  const sep = lines[i + 1] ?? "";
  return (
    line.includes("|") &&
    /^\s*\|?[\s:|-]+\|?\s*$/.test(sep) &&
    sep.includes("-")
  );
}

function wrapDisplay(s: string, maxW: number): string[] {
  const limit = Math.max(1, maxW);
  const out: string[] = [];
  let cur = "";
  let w = 0;
  for (const ch of s) {
    const cw = (ch.codePointAt(0) ?? 0) > 0xff ? 2 : 1;
    if (w + cw > limit && cur) {
      out.push(cur);
      cur = ch;
      w = cw;
    } else {
      cur += ch;
      w += cw;
    }
  }
  if (cur) out.push(cur);
  return out.length ? out : [""];
}

export function parseBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      blocks.push({ type: "code", lang, content: codeLines.join("\n") });
      continue;
    }

    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      blocks.push({ type: "heading", level: hm[1].length, content: hm[2].trim() });
      i++;
      continue;
    }

    if (/^(\s*[-*_]){3,}\s*$/.test(line) && !line.includes("**")) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (line.startsWith(">")) {
      const qlines: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) {
        qlines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", lines: qlines });
      continue;
    }

    if (/^\s*([-*+]|\d+\.)\s/.test(line)) {
      const items: { depth: number; content: string; checked?: boolean }[] = [];
      const ordered = /^\s*\d+\.\s/.test(line);
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s/.test(lines[i])) {
        const indent = lines[i].match(/^(\s*)/)?.[1].length ?? 0;
        const depth = Math.floor(indent / 2);
        const rest = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "");
        const tm = rest.match(/^\[([ xx])\]\s(.*)/);
        if (tm) items.push({ depth, content: tm[2], checked: tm[1].toLowerCase() === "x" });
        else items.push({ depth, content: rest });
        i++;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    if (isTableStart(lines, i)) {
      const rawHeaders = line
        .split("|")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const sep = lines[i + 1]
        .split("|")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const aligns: Align[] = sep.map((s) => {
        if (s.startsWith(":") && s.endsWith(":")) return "center";
        if (s.endsWith(":")) return "right";
        return "left";
      });
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(
          lines[i]
            .split("|")
            .map((s) => s.trim())
            .filter((s) => s.length > 0),
        );
        i++;
      }
      blocks.push({ type: "table", headers: rawHeaders, aligns, rows });
      continue;
    }

    if (line.trim() === "") {
      i++;
      continue;
    }

    const plines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !lines[i].startsWith(">") &&
      !/^\s*([-*+]|\d+\.)\s/.test(lines[i]) &&
      !/^(\s*[-*_]){3,}\s*$/.test(lines[i]) &&
      !isTableStart(lines, i)
    ) {
      plines.push(lines[i]);
      i++;
    }
    if (plines.length > 0) blocks.push({ type: "paragraph", content: plines.join(" ") });
  }

  return blocks;
}

function stripInline(md: string): string {
  return md
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
}

function padCell(s: string, w: number, align: Align): string {
  const sw = displayWidth(s);
  if (sw >= w) return s;
  const padN = w - sw;
  if (align === "right") return " ".repeat(padN) + s;
  if (align === "center") return " ".repeat(Math.floor(padN / 2)) + s + " ".repeat(Math.ceil(padN / 2));
  return s + " ".repeat(padN);
}

function fitColumnWidths(desired: number[], mins: number[], budget: number): number[] {
  const widths = desired.map((w, i) => Math.max(mins[i] ?? 3, w));
  let extra = widths.reduce((a, n) => a + n, 0) - budget;
  if (extra <= 0) return widths;
  const order = widths
    .map((w, i) => ({ i, slack: w - (mins[i] ?? 3) }))
    .filter((x) => x.slack > 0)
    .sort((a, b) => b.slack - a.slack);
  for (const item of order) {
    if (extra <= 0) break;
    const take = Math.min(item.slack, extra);
    widths[item.i] -= take;
    extra -= take;
  }
  if (extra > 0) {
    const order2 = widths
      .map((w, i) => ({ i, slack: w - 3 }))
      .filter((x) => x.slack > 0)
      .sort((a, b) => b.slack - a.slack);
    for (const item of order2) {
      if (extra <= 0) break;
      const take = Math.min(item.slack, extra);
      widths[item.i] -= take;
      extra -= take;
    }
  }
  return widths.map((w) => Math.max(3, w));
}

/** OpenCode-style boxed table: full grid, wrap inside cells, keep columns aligned. */
export function formatBoxedTable(
  headers: string[],
  rows: string[][],
  aligns: Align[],
  wrapW = 80,
): string[] {
  const colCount = Math.max(headers.length, ...rows.map((r) => r.length), 1);
  const cleanHeaders = Array.from({ length: colCount }, (_, c) => stripInline(headers[c] ?? ""));
  const cleanRows = rows.map((row) =>
    Array.from({ length: colCount }, (_, c) => stripInline(row[c] ?? "")),
  );
  const mins = cleanHeaders.map((h) => Math.max(3, Math.min(displayWidth(h), 16)));
  const desired: number[] = [];
  for (let c = 0; c < colCount; c++) {
    const hw = displayWidth(cleanHeaders[c] ?? "");
    const rw = cleanRows.reduce((mx, r) => Math.max(mx, displayWidth(r[c] ?? "")), 0);
    desired.push(Math.max(mins[c] ?? 3, hw, Math.min(rw, 36)));
  }
  const borderOverhead = colCount + 1 + colCount * 2;
  const budget = Math.max(colCount * 3, wrapW - borderOverhead);
  const widths = fitColumnWidths(desired, mins, budget);
  const cell = (text: string, c: number) => ` ${padCell(text, widths[c] ?? 3, aligns[c] ?? "left")} `;
  const join = (parts: string[], left: string, mid: string, right: string) =>
    `${left}${parts.join(mid)}${right}`;
  const top = join(widths.map((w) => "─".repeat(w + 2)), "┌", "┬", "┐");
  const mid = join(widths.map((w) => "─".repeat(w + 2)), "├", "┼", "┤");
  const bot = join(widths.map((w) => "─".repeat(w + 2)), "└", "┴", "┘");
  const out: string[] = [top];
  const pushLogical = (cells: string[]) => {
    const wrapped = cells.map((value, c) => wrapDisplay(value, widths[c] ?? 3));
    const height = Math.max(1, ...wrapped.map((parts) => parts.length));
    for (let line = 0; line < height; line++) {
      out.push(join(wrapped.map((parts, c) => cell(parts[line] ?? "", c)), "│", "│", "│"));
    }
  };
  pushLogical(cleanHeaders);
  out.push(mid);
  cleanRows.forEach((row, i) => {
    pushLogical(row);
    if (i < cleanRows.length - 1) out.push(mid);
  });
  out.push(bot);
  return out;
}

export function looksLikeMarkdown(text: string): boolean {
  const src = text || "";
  return /(?:^|\n)#{1,6}\s+\S|(?:^|\n)```|(?:^|\n)\s*([-*+]|\d+\.)\s|\*\*[^*]+\*\*|`[^`]+`|(?:^|\n)>\s|(?:^|\n)\s*\|.+\|\s*\n\s*\|?[\s:|-]+\|/m.test(
    src,
  );
}

let mdSyntax: ReturnType<typeof SyntaxStyle.fromStyles> | null = null;

function markdownSyntaxStyle() {
  if (!mdSyntax) {
    mdSyntax = SyntaxStyle.fromStyles({
      default: { fg: C.text },
      "markup.heading": { fg: C.yellow, bold: true },
      "markup.heading.1": { fg: C.yellow, bold: true },
      "markup.heading.2": { fg: C.yellow, bold: true },
      "markup.heading.3": { fg: C.yellow, bold: true },
      "markup.heading.4": { fg: C.yellow, bold: true },
      "markup.heading.5": { fg: C.yellow, bold: true },
      "markup.heading.6": { fg: C.yellow, bold: true },
      "markup.list": { fg: C.yellow },
      "markup.raw": { fg: C.teal },
      "markup.bold": { fg: C.text, bold: true },
      "markup.strong": { fg: C.text, bold: true },
      "markup.italic": { fg: C.subtext, italic: true },
      "markup.link": { fg: C.primary, underline: true },
      "markup.link.label": { fg: C.teal, underline: true },
      "markup.link.url": { fg: C.primary, underline: true },
      conceal: { fg: C.overlay2 },
    });
  }
  return mdSyntax;
}

const GRID_TABLE_OPTIONS = {
  style: "grid" as const,
  widthMode: "full" as const,
  columnFitter: "balanced" as const,
  wrapMode: "word" as const,
  cellPaddingX: 1,
  cellPaddingY: 0,
  borders: true,
  outerBorder: true,
  borderStyle: "single" as const,
  borderColor: C.overlay2,
  selectable: true,
};

/** Same renderer OpenCode uses: OpenTUI MarkdownRenderable + grid tables. */
export function MarkdownView({
  content,
  backgroundColor,
  wrapW,
}: {
  content: string;
  backgroundColor?: string;
  wrapW?: number;
}) {
  const bg = backgroundColor || C.bg;
  // 废弃代码（2026-09-23）：const blocks = parseBlocks(content || "");
  // 该局部变量从未被引用——实际渲染完全交给 OpenTUI MarkdownRenderable
  // （<markdown content={...}>），parseBlocks 每次渲染白算一遍全量文本，
  // 流式增量渲染下开销随内容增长。parseBlocks / formatBoxedTable 函数本身
  // 保留：Markdown.test.ts 的检测与网格表格测试仍在引用。
  return (
    <markdown
      content={content || " "}
      syntaxStyle={markdownSyntaxStyle()}
      conceal
      fg={C.text}
      bg={bg}
      width="100%"
      tableOptions={GRID_TABLE_OPTIONS}
    />
  );
}
