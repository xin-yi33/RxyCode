import { describe, expect, test } from "bun:test";
import { formatBoxedTable, looksLikeMarkdown, parseBlocks } from "./Markdown.tsx";

describe("parseBlocks", () => {
  test("parses heading code list table", () => {
    const md = `# Title

\`\`\`js
const x = 1
\`\`\`

- a
- b

| A | B |
|---|---|
| 1 | 2 |
`;
    const blocks = parseBlocks(md);
    expect(blocks.some((b) => b.type === "heading")).toBe(true);
    expect(blocks.some((b) => b.type === "code")).toBe(true);
    expect(blocks.some((b) => b.type === "list")).toBe(true);
    expect(blocks.some((b) => b.type === "table")).toBe(true);
  });

  test("looksLikeMarkdown detects headings and lists", () => {
    expect(looksLikeMarkdown("# 标题")).toBe(true);
    expect(looksLikeMarkdown("- item")).toBe(true);
    expect(looksLikeMarkdown("plain chat")).toBe(false);
  });

  test("table after a paragraph without a blank line stays a table", () => {
    const md = `确认你自己写过的小游戏有 2 个：
| 项目 | 路径 | 时间 | 内容 |
|---|---|---|---|
| 打砖块 Breakout | ~/games/breakout/index.html | 2026-09-15 | 单文件 HTML5 |
`;
    const blocks = parseBlocks(md);
    expect(blocks.some((b) => b.type === "paragraph")).toBe(true);
    const table = blocks.find((b) => b.type === "table");
    expect(table?.type).toBe("table");
    if (table?.type === "table") {
      expect(table.headers).toEqual(["项目", "路径", "时间", "内容"]);
      expect(table.rows[0]?.[0]).toBe("打砖块 Breakout");
    }
    expect(looksLikeMarkdown(md)).toBe(true);
  });

  test("boxed table keeps short headers intact and draws a grid", () => {
    const lines = formatBoxedTable(
      ["排名", "项目", "Stars", "简介"],
      [
        ["1", "obra/superpowers", "286710", "An agentic skills framework"],
        ["2", "mattpocock/skills", "262099", "Skills for Real Engineers"],
      ],
      ["left", "left", "right", "left"],
      72,
    );
    expect(lines[0]?.startsWith("┌")).toBe(true);
    expect(lines.some((line) => line.includes("Stars"))).toBe(true);
    expect(lines.join("\n")).not.toMatch(/Star\n/);
    expect(lines.at(-1)?.startsWith("└")).toBe(true);
    const rowRules = lines.filter((line) => line.startsWith("├"));
    expect(rowRules.length).toBe(2);
  });
});

describe("native OpenTUI markdown grid", () => {
  test("MarkdownRenderable grid draws a rule between every data row", async () => {
    const { MarkdownRenderable, SyntaxStyle } = await import("@opentui/core");
    const { createTestRenderer } = await import("@opentui/core/testing");
    const md = `| # | 仓库 | Stars |
|---|---|---|
| 1 | obra/superpowers | 286733 |
| 2 | mattpocock/skills | 262137 |
`;
    const setup = await createTestRenderer({ width: 72, height: 16 });
    const syntax = SyntaxStyle.fromStyles({
      default: { fg: "#ffffff" },
      "markup.heading": { fg: "#f9e2af", bold: true },
      conceal: { fg: "#555555" },
    });
    const view = new MarkdownRenderable(setup.renderer, {
      content: md,
      syntaxStyle: syntax,
      conceal: true,
      width: "100%",
      tableOptions: {
        style: "grid",
        widthMode: "full",
        columnFitter: "balanced",
        wrapMode: "word",
        cellPaddingX: 1,
        borders: true,
        outerBorder: true,
        borderStyle: "single",
        selectable: true,
      },
    });
    setup.renderer.root.add(view);
    await setup.renderOnce();
    const frame = setup.captureCharFrame();
    const midRules = (frame.match(/├/g) ?? []).length;
    const topRules = (frame.match(/┌/g) ?? []).length;
    const botRules = (frame.match(/└/g) ?? []).length;
    expect(topRules).toBeGreaterThan(0);
    expect(botRules).toBeGreaterThan(0);
    expect(midRules).toBeGreaterThanOrEqual(2);
    setup.renderer.destroy();
  });
});
