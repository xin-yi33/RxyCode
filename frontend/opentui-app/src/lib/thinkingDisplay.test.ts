import { describe, expect, test } from "bun:test";
import { nextThoughtExpanded, thoughtShowsBody } from "./thinkingDisplay.ts";

describe("finished Thought stays visible", () => {
  test("default is expanded so the first Thought body is not collapsed", () => {
    expect(nextThoughtExpanded()).toBe(true);
    expect(thoughtShowsBody({ expanded: nextThoughtExpanded(), done: true })).toBe(true);
  });
});
