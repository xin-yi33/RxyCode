import { describe, expect, test } from "bun:test";
import { clampPlanScroll, looksLikePlanDocument, parsePlanDoc, planViewportLines } from "./planDoc.ts";

describe("PlanPane helpers", () => {
  test("looksLikePlanDocument requires a heading, not a chat greeting", () => {
    expect(looksLikePlanDocument("# Neon Snake\n\n## 摘要\n做游戏")).toBe(true);
    expect(looksLikePlanDocument("你好！\n- 写代码\n- 读代码")).toBe(false);
    expect(looksLikePlanDocument("")).toBe(false);
  });

  test("parsePlanDoc uses the first markdown heading", () => {
    const doc = parsePlanDoc("# Neon Jump\n\n## Summary\nA game.");
    expect(doc.title).toBe("Neon Jump");
    expect(doc.body).toContain("## Summary");
  });

  test("parsePlanDoc falls back to joined steps", () => {
    const doc = parsePlanDoc("", ["1. inspect", "2. write plan"]);
    expect(doc.title).toBe("Plan");
    expect(doc.body).toBe("1. inspect\n2. write plan");
  });

  test("viewport stays in a nested-window band", () => {
    expect(planViewportLines(24)).toBeGreaterThanOrEqual(10);
    expect(planViewportLines(24)).toBeLessThanOrEqual(18);
    expect(planViewportLines(80)).toBe(18);
  });

  test("takeover viewport uses most of the terminal", () => {
    expect(planViewportLines(24, true)).toBe(12);
    expect(planViewportLines(40, true)).toBe(28);
    expect(planViewportLines(40, true)).toBeGreaterThan(planViewportLines(40));
  });

  test("clampPlanScroll stays in range", () => {
    expect(clampPlanScroll(-3, 20, 8)).toBe(0);
    expect(clampPlanScroll(99, 20, 8)).toBe(12);
    expect(clampPlanScroll(4, 20, 8)).toBe(4);
  });
});
