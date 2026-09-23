import { describe, expect, test } from "bun:test";
import { formatStatusBarText } from "./statusBar.ts";
import { stringWidth } from "./layout.ts";

describe("status bar formatting", () => {
  test("includes online, context, cache, mode, thinking hints", () => {
    const text = formatStatusBarText({
      connected: true,
      contextUsedK: 1.2,
      contextMaxK: 256,
      cacheSize: "12KB",
      cacheRate: "33.0%",
      mode: "build",
      thinkingExpanded: false,
      width: 120,
      modeColor: "#FF69B4",
    });
    expect(text).toContain("online");
    expect(text).toContain("上下文:1.2k/256k");
    expect(text).toContain("缓存:12KB/33.0%");
    expect(text).toContain("Build");
    expect(text).toContain("思考:关");
  });

  test("shows offline when disconnected", () => {
    const text = formatStatusBarText({
      connected: false,
      contextUsedK: 0,
      contextMaxK: 256,
      cacheSize: "0B",
      cacheRate: "0.0%",
      mode: "plan",
      thinkingExpanded: true,
      width: 80,
      modeColor: "#00ff7f",
    });
    expect(text).toContain("offline");
    expect(text).toContain("思考:开");
    expect(text).toContain("Plan");
  });

  test("shows current team role and budget on the right", () => {
    const text = formatStatusBarText({
      connected: true,
      contextUsedK: 1,
      contextMaxK: 256,
      cacheSize: "0B",
      cacheRate: "0.0%",
      mode: "build",
      thinkingExpanded: false,
      width: 160,
      modeColor: "#FF69B4",
      teamRole: "architect",
      teamBudget: "187k/500k",
    });
    expect(text).toContain("[architect]");
    expect(text).toContain("187k/500k");
  });

  test("fits CJK segments to display width so the bar stays one row", () => {
    const text = formatStatusBarText({
      connected: true,
      contextUsedK: 41.1,
      contextMaxK: 1049,
      cacheSize: "907.0k",
      cacheRate: "96.2%",
      mode: "build",
      thinkingExpanded: false,
      width: 80,
      modeColor: "#FF69B4",
    });
    expect(stringWidth(text)).toBeLessThanOrEqual(78);
    expect(text.includes("\n")).toBe(false);
  });
});
