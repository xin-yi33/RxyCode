import { describe, expect, test } from "bun:test";
import { isPromptNewlineKey, isPromptSubmitKey, normalizePromptSubmitText } from "./promptSubmitKey.ts";

describe("isPromptSubmitKey", () => {
  test("matches return/kpenter", () => {
    expect(isPromptSubmitKey({ name: "return" })).toBe(true);
    expect(isPromptSubmitKey({ name: "kpenter" })).toBe(true);
    expect(isPromptSubmitKey({ name: "linefeed" })).toBe(false);
  });

  test("matches bare CR (ConPTY Enter), not LF (Shift+Enter)", () => {
    expect(isPromptSubmitKey({ name: "", sequence: "\r" })).toBe(true);
    expect(isPromptSubmitKey({ name: "", sequence: "\n" })).toBe(false);
    expect(isPromptSubmitKey({ name: "", raw: "\r\n" })).toBe(true);
  });

  test("ignores Shift/Meta/Ctrl Enter", () => {
    expect(isPromptSubmitKey({ name: "return", shift: true })).toBe(false);
    expect(isPromptSubmitKey({ name: "return", meta: true })).toBe(false);
    expect(isPromptSubmitKey({ name: "return", ctrl: true })).toBe(false);
  });
});

describe("isPromptNewlineKey", () => {
  test("matches Shift+Enter and ConPTY LF", () => {
    expect(isPromptNewlineKey({ name: "return", shift: true })).toBe(true);
    expect(isPromptNewlineKey({ name: "linefeed" })).toBe(true);
    expect(isPromptNewlineKey({ name: "", sequence: "\n" })).toBe(true);
    expect(isPromptNewlineKey({ name: "return" })).toBe(false);
  });

  test("matches Ctrl+Enter as newline (2026-09-23 用户习惯)", () => {
    expect(isPromptNewlineKey({ name: "return", ctrl: true })).toBe(true);
    expect(isPromptNewlineKey({ name: "kpenter", ctrl: true })).toBe(true);
    // Ctrl+Enter 不得误判为发送
    expect(isPromptSubmitKey({ name: "return", ctrl: true })).toBe(false);
  });

  test("Meta/Super+Enter 既不是换行也不是发送", () => {
    expect(isPromptNewlineKey({ name: "return", meta: true })).toBe(false);
    expect(isPromptNewlineKey({ name: "return", super: true })).toBe(false);
  });
});

describe("normalizePromptSubmitText", () => {
  test("strips trailing newlines from failed Enter inserts", () => {
    expect(normalizePromptSubmitText("/model\n")).toBe("/model");
    expect(normalizePromptSubmitText("/mod\r\n")).toBe("/mod");
    expect(normalizePromptSubmitText("  /model  \n\n")).toBe("/model");
  });
});
