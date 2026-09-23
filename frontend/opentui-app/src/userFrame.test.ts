import { describe, expect, test } from "bun:test";
import { wrapContentLines } from "./layout.ts";

/** OpenCode-style bubble: content rows plus one pad row above and below. */
export function userBubbleRowCount(content: string, wrapW: number): number {
  return wrapContentLines(content, wrapW).length + 2;
}

export function userBubbleBarGlyph(): string {
  return "\u258E";
}

describe("UserMessage bubble rows", () => {
  test("multiline content is one row per line", () => {
    const content = "第一行\n第二行\n第三行";
    expect(userBubbleRowCount(content, 80)).toBe(5);
  });

  test("soft wrap increases rows", () => {
    const long = "x".repeat(50);
    expect(userBubbleRowCount(long, 20)).toBeGreaterThan(3);
  });

  test("bar glyph is the quarter block, not a full █ cell", () => {
    expect(userBubbleBarGlyph()).toBe("▎");
    expect(userBubbleBarGlyph()).not.toBe("█");
  });
});
