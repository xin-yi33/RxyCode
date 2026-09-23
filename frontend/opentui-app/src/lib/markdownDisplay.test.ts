import { describe, expect, test, beforeEach } from "bun:test";
import {
  applyComposerMarkdownArg,
  composerMarkdownEnabled,
  cycleComposerMarkdown,
  resetComposerMarkdown,
  setComposerMarkdown,
} from "./markdownDisplay.ts";

describe("composer markdown preference", () => {
  beforeEach(() => {
    resetComposerMarkdown();
  });

  test("defaults on", () => {
    expect(composerMarkdownEnabled()).toBe(true);
  });

  test("cycles and accepts on/off", () => {
    expect(cycleComposerMarkdown()).toEqual({ enabled: false });
    expect(applyComposerMarkdownArg("on")).toEqual({ enabled: true });
    expect(applyComposerMarkdownArg("off")).toEqual({ enabled: false });
    setComposerMarkdown(true);
    expect(composerMarkdownEnabled()).toBe(true);
  });
});
