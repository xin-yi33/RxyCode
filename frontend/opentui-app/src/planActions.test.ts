import { describe, expect, test } from "bun:test";
import {
  classifyPlanComposer,
  implementPlanPrompt,
  isPlanShortcutKey,
  planLineColor,
  requestChangesPrompt,
} from "./planActions.ts";

describe("planActions", () => {
  test("classifies Grok-style single-letter shortcuts", () => {
    expect(classifyPlanComposer("a")).toEqual({ kind: "approve" });
    expect(classifyPlanComposer("s")).toEqual({ kind: "request_changes" });
    expect(classifyPlanComposer("c")).toEqual({ kind: "comment" });
    expect(classifyPlanComposer("y")).toEqual({ kind: "copy" });
    expect(classifyPlanComposer("q")).toEqual({ kind: "quit" });
    expect(isPlanShortcutKey("a")).toBe("approve");
  });

  test("start-build phrases are not treated as plan edits", () => {
    expect(classifyPlanComposer("开始吧")).toEqual({ kind: "start_build" });
    expect(classifyPlanComposer("implement it now")).toEqual({ kind: "start_build" });
    expect(classifyPlanComposer("把标题改短一点")).toEqual({ kind: "revise" });
  });

  test("implement prompt keeps the approved plan body", () => {
    expect(implementPlanPrompt("# Title\n1. do")).toContain("# Title");
  });

  test("request-changes prompt keeps the current plan body", () => {
    expect(requestChangesPrompt("# Title\n1. do")).toContain("# Title");
    expect(requestChangesPrompt("# Title")).toContain("修订");
    expect(requestChangesPrompt("# Title", "改成贪吃蛇")).toContain("改成贪吃蛇");
    expect(requestChangesPrompt("# Title", "s")).not.toContain("s\n");
  });

  test("planLineColor maps markdown kinds", () => {
    expect(planLineColor("# Title")).toBe("heading");
    expect(planLineColor("1. step")).toBe("list");
    expect(planLineColor("> note")).toBe("quote");
    expect(planLineColor("hello")).toBe("text");
  });
});
