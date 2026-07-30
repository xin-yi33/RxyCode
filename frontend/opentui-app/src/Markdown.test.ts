import { describe, expect, test } from "bun:test";
import { parseBlocks } from "./Markdown.tsx";

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
});
