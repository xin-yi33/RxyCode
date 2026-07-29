import { describe, expect, test } from "bun:test";
import {
  WORDMARK,
  WELCOME_ROWS,
  WELCOME_LINES,
  SHORTCUTS_HINT,
  BRAND_LIGHT,
  BRAND_HOT,
  BRAND_MUTED,
  centerPad,
  getWordmark,
  logoInkForRow,
  LOGO_INK_TOP,
  LOGO_INK_BODY,
  LOGO_FIELD_BG,
} from "./brand.ts";

describe("classic brand freeze (Ink original)", () => {
  test("WORDMARK has 7 Unicode block lines", () => {
    expect(WORDMARK).toHaveLength(7);
    expect(WORDMARK[0]).toContain("██");
    expect(getWordmark()[0]).not.toContain("#");
  });

  test("colors match original Ink exactly", () => {
    expect(LOGO_INK_TOP).toBe("#FFB6C1");
    expect(LOGO_INK_BODY).toBe("#FF69B4");
    expect(BRAND_LIGHT).toBe("#FFB6C1");
    expect(BRAND_HOT).toBe("#FF69B4");
    expect(LOGO_FIELD_BG).toBe("#000000");
    expect(logoInkForRow(0)).toBe("#FFB6C1");
    expect(logoInkForRow(1)).toBe("#FF69B4");
  });

  test("welcome matches Ink ChatPanel split colors", () => {
    const blob = WELCOME_ROWS.flatMap((r) => r.parts.map((p) => p.text)).join("\n");
    expect(blob).toContain("你好！我是 RxyCode");
    expect(blob).toContain("代码开发");
    expect(blob).toContain("有什么我可以帮你的？");
    expect(blob).not.toContain("快捷键");
    expect(SHORTCUTS_HINT).toContain("快捷键");
    expect(WELCOME_ROWS[0].parts[0].fg).toBe("#FFB6C1");
    const cap = WELCOME_ROWS[1].parts;
    expect(cap[1].fg).toBe("#FF69B4");
    expect(cap[1].bold).toBe(true);
    expect(cap[2].fg).toBe("#aaaaaa");
    expect(WELCOME_LINES.length).toBe(WELCOME_ROWS.length);
    expect(BRAND_MUTED).toBe("#555555");
  });

  test("centerPad centers within columns", () => {
    const line = centerPad("RXY", 9);
    expect(line.startsWith("   ")).toBe(true);
    expect(line.trim()).toBe("RXY");
  });
});
