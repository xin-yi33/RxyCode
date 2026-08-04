import { describe, expect, test } from "bun:test";
import { isPromptSubmitKey, normalizePromptSubmitText } from "./promptSubmitKey.ts";

describe("isPromptSubmitKey", () => {
  test("matches return/linefeed/kpenter", () => {
    expect(isPromptSubmitKey({ name: "return" })).toBe(true);
    expect(isPromptSubmitKey({ name: "linefeed" })).toBe(true);
    expect(isPromptSubmitKey({ name: "kpenter" })).toBe(true);
  });

  test("matches bare CR/LF sequences (ConPTY)", () => {
    expect(isPromptSubmitKey({ name: "", sequence: "\r" })).toBe(true);
    expect(isPromptSubmitKey({ name: "", sequence: "\n" })).toBe(true);
    expect(isPromptSubmitKey({ name: "", raw: "\r\n" })).toBe(true);
  });

  test("ignores Shift/Meta/Ctrl Enter", () => {
    expect(isPromptSubmitKey({ name: "return", shift: true })).toBe(false);
    expect(isPromptSubmitKey({ name: "return", meta: true })).toBe(false);
    expect(isPromptSubmitKey({ name: "return", ctrl: true })).toBe(false);
  });
});

describe("normalizePromptSubmitText", () => {
  test("strips trailing newlines from failed Enter inserts", () => {
    expect(normalizePromptSubmitText("/model\n")).toBe("/model");
    expect(normalizePromptSubmitText("/mod\r\n")).toBe("/mod");
    expect(normalizePromptSubmitText("  /model  \n\n")).toBe("/model");
  });
});
