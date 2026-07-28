import { describe, expect, test } from "bun:test";
import { WORDMARK, WELCOME_LINES, centerPad } from "./brand.ts";

describe("classic brand freeze", () => {
  test("WORDMARK has 7 pink block lines", () => {
    expect(WORDMARK).toHaveLength(7);
    expect(WORDMARK[0]).toContain("██");
  });

  test("welcome keeps Chinese capability list and shortcuts", () => {
    const blob = WELCOME_LINES.map((l) => l.text).join("\n");
    expect(blob).toContain("你好！我是 RxyCode");
    expect(blob).toContain("代码开发");
    expect(blob).toContain("有什么我可以帮你的？");
    expect(blob).toContain("快捷键");
  });

  test("centerPad centers within columns", () => {
    const line = centerPad("RXY", 9);
    expect(line.startsWith("   ")).toBe(true);
    expect(line.trim()).toBe("RXY");
  });
});
