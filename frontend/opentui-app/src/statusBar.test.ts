import { describe, expect, test } from "bun:test";
import { formatStatusBarText } from "./statusBar.ts";

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
});
