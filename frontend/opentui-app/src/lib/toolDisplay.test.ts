import { describe, expect, test } from "bun:test";
import {
  buildEditDiff,
  classifyTool,
  diffCounts,
  fileLabel,
  genericSummary,
  groupDiffHunks,
  parseToolArgs,
  readTargets,
  selectDiffPreview,
  selectLinePreview,
  serializeToolArgs,
  shouldHideToolCard,
  isPlanMdPath,
  toolCommand,
} from "./toolDisplay.ts";
import { EDIT_PREVIEW_LINES, previewLimitForFamily, TOOL_PREVIEW_LINES } from "./toolCardDisplay.ts";

describe("toolDisplay", () => {
  test("hides the internal history tool from the chat", () => {
    expect(shouldHideToolCard("history", "[no matching history entries]")).toBe(true);
    expect(shouldHideToolCard("final_answer", "你好")).toBe(true);
    expect(shouldHideToolCard("final-answer", "你好")).toBe(true);
    expect(shouldHideToolCard("bash", "ok")).toBe(false);
  });

  test("classifies edit/read/bash/generic families", () => {
    expect(classifyTool("edit")).toBe("edit");
    expect(classifyTool("write")).toBe("edit");
    expect(classifyTool("write_file")).toBe("edit");
    expect(classifyTool("patch")).toBe("edit");
    expect(classifyTool("read")).toBe("read");
    expect(classifyTool("grep")).toBe("read");
    expect(classifyTool("bash")).toBe("bash");
    expect(classifyTool("websearch")).toBe("generic");
  });

  test("parses camelCase edit args and builds red/green counts", () => {
    const args = parseToolArgs({
      filePath: "counter.py",
      oldString: "a = 1\nb = 2",
      newString: "a = 1\nb = 3",
    });
    const diff = buildEditDiff("edit", args);
    const counts = diffCounts(diff);
    expect(counts.removed).toBe(1);
    expect(counts.added).toBe(1);
    expect(diff.some((l) => l.kind === "del" && l.text === "b = 2")).toBe(true);
    expect(diff.some((l) => l.kind === "add" && l.text === "b = 3")).toBe(true);
  });

  test("groups consecutive add/del lines into solid hunks", () => {
    const groups = groupDiffHunks([
      { kind: "del", text: "old" },
      { kind: "del", text: "also" },
      { kind: "add", text: "new" },
      { kind: "add", text: "too" },
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toEqual({ kind: "del", lines: [{ kind: "del", text: "old" }, { kind: "del", text: "also" }] });
    expect(groups[1]?.kind).toBe("add");
    expect(groups[1]?.lines).toHaveLength(2);
  });

  test("diff preview keeps +/- counts but only shows a hunk", () => {
    const written = Array.from({ length: 40 }, (_, i) => `line ${i}`);
    const diff = buildEditDiff("write", { filePath: "a.py", content: written.join("\n") });
    expect(diffCounts(diff).added).toBe(40);
    const preview = selectDiffPreview(diff, 12);
    expect(preview.lines).toHaveLength(12);
    expect(preview.clipped).toBe(28);
    expect(preview.lines.every((l) => l.kind === "add")).toBe(true);
  });

  test("write shows every new line as an addition", () => {
    const diff = buildEditDiff("write", { filePath: "a.py", content: "one\ntwo" });
    expect(diff).toEqual([
      { kind: "add", text: "one" },
      { kind: "add", text: "two" },
    ]);
  });

  test("grep and read both surface as read: targets", () => {
    expect(readTargets("read", { filePath: "src/app.ts" }, "")).toEqual(["src/app.ts"]);
    expect(
      readTargets(
        "grep",
        { pattern: "TODO", path: "src" },
        "src/a.ts:3: TODO\nsrc/b.ts:9: TODO",
      ),
    ).toEqual(["src/a.ts", "src/b.ts"]);
  });

  test("bash keeps the raw command from a plain string", () => {
    expect(toolCommand(parseToolArgs("python counter.py"))).toBe("python counter.py");
    expect(toolCommand(parseToolArgs({ command: "dir" }))).toBe("dir");
    expect(toolCommand(parseToolArgs({ raw: "echo hi" }))).toBe("echo hi");
  });

  test("serialize then parse round-trips objects", () => {
    const raw = serializeToolArgs({ filePath: "x.ts", content: "hi" });
    expect(parseToolArgs(raw).filePath).toBe("x.ts");
  });

  test("non-edit tool preview is half of edit", () => {
    expect(TOOL_PREVIEW_LINES).toBe(6);
    expect(EDIT_PREVIEW_LINES).toBe(12);
    expect(previewLimitForFamily("generic")).toBe(6);
    expect(previewLimitForFamily("bash")).toBe(6);
    expect(previewLimitForFamily("edit")).toBe(12);
  });

  test("selectLinePreview keeps the first chunk and counts the tail", () => {
    const lines = Array.from({ length: 20 }, (_, i) => `L${i}`);
    const preview = selectLinePreview(lines, 12);
    expect(preview.lines).toHaveLength(12);
    expect(preview.clipped).toBe(8);
    expect(preview.lines[0]).toBe("L0");
    expect(selectLinePreview(["a", "b"], 12).clipped).toBe(0);
  });

  test("generic summaries follow Grok-style labels", () => {
    expect(genericSummary("glob", { pattern: "**/*.py" })).toBe("glob: **/*.py");
    expect(genericSummary("websearch", { query: "sha" })).toBe("search: sha");
    expect(genericSummary("ls", { path: "src" })).toBe("ls: src");
  });

  test("plan.md keeps a short session-relative label", () => {
    expect(isPlanMdPath("sessions/abc/plan.md")).toBe(true);
    expect(isPlanMdPath("readme.md")).toBe(false);
    expect(fileLabel("C:/Users/x/.RxyCode/sessions/abc/plan.md")).toBe("sessions/abc/plan.md");
    expect(fileLabel("src/app.ts")).toBe("app.ts");
  });
});
