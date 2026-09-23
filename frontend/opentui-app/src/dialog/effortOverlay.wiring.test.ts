import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));

describe("model → effort overlay wiring", () => {
  test("DialogModel does not close itself after a successful switch", () => {
    const src = readFileSync(path.join(dir, "DialogModel.tsx"), "utf8");
    const success = src.slice(src.indexOf("setCurrent(opt.value)"));
    expect(success).toMatch(/effort_options/);
    expect(success).not.toMatch(/onClose\(\)/);
  });

  test("settings dialogs replace /model with Select effort when gears exist", () => {
    const src = readFileSync(path.join(dir, "useSettingsDialogs.tsx"), "utf8");
    expect(src).toMatch(/planAfterModelSwitch/);
    expect(src).toMatch(/continueAfterModelChange/);
    expect(src).toMatch(/openEffort\(\)/);
  });

  test("DialogEffort title stays Select effort and Default is prepended outside buildOptions", () => {
    const src = readFileSync(path.join(dir, "DialogEffort.tsx"), "utf8");
    expect(src).toMatch(/SELECT_EFFORT_TITLE/);
    expect(src).toMatch(/buildEffortPickerOptions\(built\.options\)/);
    expect(src).not.toMatch(/title="选择思考强度"/);
  });

  test("add-model success leaves overlay replacement to the parent", () => {
    const src = readFileSync(path.join(dir, "DialogAddModel.tsx"), "utf8");
    expect(src).toMatch(/onDone\(/);
    const saveBatch = src.slice(src.indexOf("const saveBatch"), src.indexOf("const save ="));
    const save = src.slice(src.indexOf("const save ="), src.indexOf("if (stage === \"provider\")"));
    expect(saveBatch).not.toMatch(/onClose\(\)/);
    expect(save).not.toMatch(/onClose\(\)/);
    expect(src).toMatch(/添加成功/);
  });

  test("add-model done opens /model list instead of effort overlay", () => {
    const src = readFileSync(path.join(dir, "useSettingsDialogs.tsx"), "utf8");
    const addBlock = src.slice(src.indexOf("const openAddModel"), src.indexOf("const openModel ="));
    expect(addBlock).toMatch(/openModelRef\.current\(\)/);
    expect(addBlock).not.toMatch(/continueAfterModelChange/);
  });

  test("DialogPrompt uses a visible native caret and does not intercept typing", () => {
    const src = readFileSync(path.join(dir, "DialogPrompt.tsx"), "utf8");
    expect(src).not.toMatch(/showCursor=\{false\}/);
    expect(src).not.toMatch(/Focus sink last/);
    expect(src).not.toMatch(/drawnBlockCursor: true/);
    expect(src).toMatch(/Do not intercept printable/);
    expect(src).not.toMatch(/left:\s*-10000/);
    expect(src).toMatch(/cursorColor/);
    expect(src.includes("d.slice(0, -1)")).toBe(false);
    expect(src).toMatch(/<input/);
  });

  test("effort options share fetchModels (stdio models/list), not a second HTTP GET", () => {
    const src = readFileSync(path.join(dir, "api.ts"), "utf8");
    const live = src.slice(src.indexOf("export async function fetchEffortOptions"), src.indexOf("废弃代码（2026-09-21）：fetchEffortOptions"));
    expect(live).toMatch(/fetchModels\(\)/);
    expect(live).not.toMatch(/axios\.get/);
    expect(src).toMatch(/废弃代码（2026-09-21）：fetchEffortOptions 旧实现只打 HTTP GET \/models/);
  });
});
