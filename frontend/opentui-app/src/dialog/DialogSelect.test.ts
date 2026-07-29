import { describe, expect, test } from "bun:test";
import {
  buildSelectRows,
  shouldApplyMouseHover,
  textFromKeyEvent,
  type DialogSelectOption,
} from "./DialogSelect.tsx";

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

describe("buildSelectRows", () => {
  const opts: DialogSelectOption[] = [
    { id: "1", title: "/clear", description: "清除对话上下文", category: "会话", value: "/clear" },
    { id: "2", title: "/build", description: "进入构建模式", category: "Agent", value: "/build" },
    { id: "3", title: "/addmodel", description: "添加新模型", category: "Agent", value: "/addmodel" },
  ];

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
