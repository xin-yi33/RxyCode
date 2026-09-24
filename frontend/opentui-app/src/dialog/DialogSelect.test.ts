import { describe, expect, test } from "bun:test";
import {
  buildSelectRows,
  formatSearchFieldDisplay,
  scheduleAfterMouse,
  shouldApplyMouseHover,
  textFromKeyEvent,
  type DialogSelectOption,
} from "./DialogSelect.tsx";

describe("scheduleAfterMouse", () => {
  test("does not run inside the mouse handler", async () => {
    let ran = false;
    scheduleAfterMouse(() => {
      ran = true;
    });
    expect(ran).toBe(false);
    await Promise.resolve();
    expect(ran).toBe(true);
  });
});

describe("shouldApplyMouseHover", () => {
  test("keyboard mode blocks hover (clear→build snap-back fix)", () => {
    expect(shouldApplyMouseHover("keyboard")).toBe(false);
  });
  test("mouse mode allows hover", () => {
    expect(shouldApplyMouseHover("mouse")).toBe(true);
  });
});

describe("textFromKeyEvent", () => {
  test("single letter", () => {
    expect(textFromKeyEvent({ name: "m", raw: "m" })).toEqual({ text: "m", submit: false });
  });
  test("PTY burst 'model'", () => {
    expect(textFromKeyEvent({ name: "", raw: "model" })).toEqual({ text: "model", submit: false });
  });
  test("PTY burst 'model\\r' submits", () => {
    expect(textFromKeyEvent({ name: "", raw: "model\r" })).toEqual({ text: "model", submit: true });
  });
  test("return alone submits", () => {
    expect(textFromKeyEvent({ name: "return", raw: "\r" })).toEqual({ text: "", submit: true });
  });
  test("arrows ignored", () => {
    expect(textFromKeyEvent({ name: "down", raw: "\x1b[B" })).toBeNull();
  });
});

describe("formatSearchFieldDisplay", () => {
  test("cursor follows end of typed filter (not first char)", () => {
    expect(formatSearchFieldDisplay("", "搜索模型")).toEqual({
      text: "搜索模型",
      isPlaceholder: true,
    });
    expect(formatSearchFieldDisplay("glm", "搜索模型")).toEqual({
      text: "glm",
      isPlaceholder: false,
    });
  });
});

describe("buildSelectRows", () => {
  const opts: DialogSelectOption[] = [
    { id: "1", title: "/clear", description: "清除对话上下文", category: "会话", value: "/clear" },
    { id: "2", title: "/build", description: "进入构建模式", category: "Agent", value: "/build" },
    { id: "3", title: "/addmodel", description: "添加新模型", category: "Agent", value: "/addmodel" },
  ];

  test("empty filter preserves caller order not alphabetical title", () => {
    const recency: DialogSelectOption[] = [
      { id: "1", title: "pdf格式转换", footer: "now", category: "Today", value: "1" },
      { id: "2", title: "hi", footer: "3h", category: "Today", value: "2" },
      { id: "3", title: "hi", footer: "10h", category: "Today", value: "3" },
    ];
    const { rows } = buildSelectRows(recency, "", ["Today"]);
    const titles = rows.filter((r) => r.kind === "item").map((r) => (r.kind === "item" ? r.option.title : ""));
    expect(titles).toEqual(["pdf格式转换", "hi", "hi"]);
  });

  test("empty filter keeps category headers on own rows", () => {
    const { rows } = buildSelectRows(opts, "", ["会话", "Agent"]);
    expect(rows[0]).toEqual({ kind: "header", category: "会话", key: "h-会话" });
    expect(rows.some((r) => r.kind === "item" && r.option.title === "/clear")).toBe(true);
    expect(rows.some((r) => r.kind === "header" && r.category === "Agent")).toBe(true);
  });

  test("filter flattens without headers", () => {
    const { rows } = buildSelectRows(opts, "build", ["会话", "Agent"]);
    expect(rows.every((r) => r.kind === "item")).toBe(true);
    expect(rows[0]?.kind === "item" && rows[0].option.title).toBe("/build");
  });

  test("grouped flat order matches visual rows so Enter selects the highlighted model", () => {
    const mixed: DialogSelectOption[] = [
      { id: "go/glm", title: "glm · opencode.ai", category: "OpenCode Go", value: "go/glm" },
      { id: "arc/glm", title: "glm · api.arc-bench.com", category: "api.arc-bench.com", value: "arc/glm" },
      { id: "go/kimi", title: "kimi · opencode.ai", category: "OpenCode Go", value: "go/kimi" },
      { id: "arc/kimi", title: "kimi · api.arc-bench.com", category: "api.arc-bench.com", value: "arc/kimi" },
    ];
    const { flat, rows } = buildSelectRows(mixed, "", ["api.arc-bench.com", "OpenCode Go"]);
    const visual = rows.filter((r) => r.kind === "item").map((r) => r.kind === "item" ? r.option.value : "");
    expect(flat.map((o) => o.value)).toEqual(visual);
    expect(flat.map((o) => o.value)).toEqual([
      "arc/glm",
      "arc/kimi",
      "go/glm",
      "go/kimi",
    ]);
    expect(flat[0]?.value).toBe("arc/glm");
    expect(flat[2]?.value).toBe("go/glm");
  });

  test("filter 'model' ranks /model before /addmodel", () => {
    const { rows } = buildSelectRows(
      [
        { id: "1", title: "/addmodel", description: "添加", category: "Agent", value: "a" },
        { id: "2", title: "/model", description: "切换", category: "Agent", value: "m" },
        { id: "3", title: "/models", description: "列表", category: "Agent", value: "ms" },
      ],
      "model",
    );
    expect(rows[0]?.kind === "item" && rows[0].option.title).toBe("/model");
  });
});
