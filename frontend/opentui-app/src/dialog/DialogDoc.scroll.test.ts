import { describe, expect, test } from "bun:test";
import { clampDocScroll, docViewportLines } from "./DialogDoc.tsx";

describe("DialogDoc viewport math", () => {
  test("help viewport stays smaller than the terminal", () => {
    expect(docViewportLines("help", 24)).toBe(14);
    expect(docViewportLines("help", 40)).toBe(22);
    expect(docViewportLines("tutorial", 24)).toBe(12);
  });

  test("clampDocScroll stops at the last page", () => {
    expect(clampDocScroll(-3, 40, 10)).toBe(0);
    expect(clampDocScroll(3, 40, 10)).toBe(3);
    expect(clampDocScroll(99, 40, 10)).toBe(30);
    expect(clampDocScroll(0, 5, 10)).toBe(0);
  });
});
