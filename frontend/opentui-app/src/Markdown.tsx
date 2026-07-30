/**
 * OpenTUI Markdown renderer — local copy of Ink Markdown capabilities
 * (headings, lists, code, tables, quotes). Does NOT import frontend/src.
 */
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

    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) &&
      lines[i + 1].includes("-")
    ) {
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
      !/^(\s*[-*_]){3,}\s*$/.test(lines[i])
    ) {
      plines.push(lines[i]);
      i++;
    }
    if (plines.length > 0) blocks.push({ type: "paragraph", content: plines.join(" ") });
  }

  return blocks;
}

const HEADING_COLORS = [C.primary, C.yellow, C.mauve, C.teal, C.subtext, C.overlay2];

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

/** Render markdown to colored OpenTUI nodes. Only call when message is done (stable). */
export function MarkdownView({ content }: { content: string }) {
  const blocks = parseBlocks(content || "");
  if (blocks.length === 0) {
    return (
      <text fg={C.text} selectable>
        {content}
      </text>
    );
  }

  return (
    <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
      {blocks.map((b, idx) => {
        switch (b.type) {
          case "heading": {
            const color = HEADING_COLORS[Math.min(b.level - 1, 5)];
            return (
              <text key={idx} selectable>
                <span fg={color} attributes={1}>
                  {"  "}
                  {stripInline(b.content)}
                </span>
              </text>
            );
          }
          case "code":
            return (
              <box key={idx} style={{ flexDirection: "column", paddingLeft: 2, backgroundColor: C.surface0 }}>
                {b.lang ? (
                  <text fg={C.overlay2} selectable>
                    {b.lang}
                  </text>
                ) : null}
                {b.content.split("\n").map((line, li) => (
                  <text key={li} fg={C.teal} selectable>
                    {line || " "}
                  </text>
                ))}
              </box>
            );
          case "list":
            return (
              <box key={idx} style={{ flexDirection: "column" }}>
                {b.items.map((item, ii) => {
                  const bullet =
                    item.checked === true
                      ? "☑"
                      : item.checked === false
                        ? "☐"
                        : b.ordered
                          ? `${ii + 1}.`
                          : "•";
                  return (
                    <text key={ii} selectable>
                      <span fg={C.yellow}>
                        {" ".repeat(item.depth * 2 + 2)}
                        {bullet}{" "}
                      </span>
                      <span fg={C.text}>{stripInline(item.content)}</span>
                    </text>
                  );
                })}
              </box>
            );
          case "blockquote":
            return (
              <box key={idx} style={{ flexDirection: "column", paddingLeft: 2 }}>
                {b.lines.map((ql, qi) => (
                  <text key={qi} selectable>
                    <span fg={C.mauve}>{"│ "}</span>
                    <span fg={C.subtext}>{stripInline(ql)}</span>
                  </text>
                ))}
              </box>
            );
          case "table": {
            const colCount = Math.max(b.headers.length, ...b.rows.map((r) => r.length), 1);
            const widths: number[] = [];
            for (let c = 0; c < colCount; c++) {
              const hw = displayWidth(b.headers[c] ?? "");
              const rw = b.rows.reduce((mx, r) => Math.max(mx, displayWidth(r[c] ?? "")), 0);
              widths.push(Math.max(hw, rw, 3));
            }
            const fmt = (cells: string[], bold: boolean) =>
              cells
                .map((cell, c) => padCell(stripInline(cell ?? ""), widths[c] ?? 3, b.aligns[c] ?? "left"))
                .join(" │ ");
            const headerLine = fmt(
              Array.from({ length: colCount }, (_, c) => b.headers[c] ?? ""),
              true,
            );
            const rule = widths.map((w) => "─".repeat(w)).join("─┼─");
            return (
              <box key={idx} style={{ flexDirection: "column", paddingLeft: 2 }}>
                <text fg={BRAND_TABLE_HEADER} attributes={1} selectable>
                  {headerLine}
                </text>
                <text fg={C.borderDim} selectable>
                  {rule}
                </text>
                {b.rows.map((row, ri) => (
                  <text key={ri} fg={C.text} selectable>
                    {fmt(
                      Array.from({ length: colCount }, (_, c) => row[c] ?? ""),
                      false,
                    )}
                  </text>
                ))}
              </box>
            );
          }
          case "hr":
            return (
              <text key={idx} fg={C.borderDim} selectable>
                {"  "}
                {"─".repeat(40)}
              </text>
            );
          case "paragraph":
            return (
              <text key={idx} fg={C.text} selectable>
                {"  "}
                {stripInline(b.content)}
              </text>
            );
          default:
            return null;
        }
      })}
    </box>
  );
}

const BRAND_TABLE_HEADER = C.primary;
