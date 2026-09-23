import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { C } from "./theme.ts";
import { EFFORT_CHIP_FG } from "./dialog/effortPicker.ts";

describe("OpenTUI effort chip chrome", () => {
  test("chip color matches OpenCode yellow", () => {
    expect(EFFORT_CHIP_FG).toBe("#f9e2af");
    expect(C.yellow).toBe("#f9e2af");
  });

  test("header renders yellow effort chip; composer stays original Ready box", () => {
    const src = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "App.tsx"),
      "utf8",
    );
    expect(src).toMatch(/formatComposerEffortChip/);
    expect(src).toMatch(/EFFORT_CHIP_FG/);
    expect(src).toMatch(/minHeight: 2 \+ inputHeight/);
    expect(src).toMatch(/formatInputHint\(isStreaming, followupCount\)/);
    const composer = src.slice(src.indexOf("minHeight: 2 + inputHeight"));
    expect(composer).toMatch(/处理中，回车加入队列/);
    expect(composer.slice(0, composer.indexOf("Classic: status"))).not.toMatch(/effortChip/);
  });
});
