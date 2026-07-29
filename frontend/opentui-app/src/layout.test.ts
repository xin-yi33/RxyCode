import { describe, expect, test } from "bun:test";
import {
  inputVisibleLines,
  needsInputScroll,
  numInputLines,
  stringWidth,
  wrapContentLines,
} from "./layout.ts";

describe("layout stringWidth / wrap", () => {
  test("ascii and CJK widths", () => {
    expect(stringWidth("abc")).toBe(3);
    expect(stringWidth("你好")).toBe(4);
  });

  test("numInputLines wraps", () => {
    expect(numInputLines("abcdefghijk", 10)).toBe(2);
    expect(numInputLines("a\nb\nc", 80)).toBe(3);
  });

  test("wrapContentLines paints one row per wrapped segment", () => {
    const lines = wrapContentLines("hello\nworld", 80);
    expect(lines).toEqual(["hello", "world"]);
    expect(wrapContentLines("一二三四五六七八九十", 8).length).toBeGreaterThan(1);
  });

  test("input grows then caps for scroll", () => {
    const short = "hi";
    expect(inputVisibleLines(short, 40)).toBe(1);
    const many = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
    expect(inputVisibleLines(many, 80)).toBe(10);
    expect(needsInputScroll(many, 80)).toBe(true);
  });
});
