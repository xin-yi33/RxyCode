import { describe, expect, test } from "bun:test";
import { wrapContentLines } from "./layout.ts";

/** Pure helper mirroring UserMessage row count (bar rows = content lines + 2). */
export function userFrameBarCount(content: string, wrapW: number): number {
  return wrapContentLines(content, wrapW).length + 2;
}

describe("UserMessage frame bars", () => {
  test("multiline content gets a bar per content line plus top/bottom", () => {
    const content = "第一行\n第二行\n第三行";
    expect(userFrameBarCount(content, 80)).toBe(5);
  });

  test("soft wrap increases bar rows", () => {
    const long = "x".repeat(50);
    expect(userFrameBarCount(long, 20)).toBeGreaterThan(3);
  });
});
