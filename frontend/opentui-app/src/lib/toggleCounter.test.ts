import { describe, expect, test } from "bun:test";
import { ToggleCounter } from "./toggleCounter.ts";

describe("ToggleCounter", () => {
  test("starts collapsed at 0 and flips on odd counts", () => {
    const counter = new ToggleCounter();
    expect(counter.count).toBe(0);
    expect(counter.expanded).toBe(false);
    expect(counter.increment()).toBe(1);
    expect(counter.expanded).toBe(true);
    expect(counter.increment()).toBe(2);
    expect(counter.expanded).toBe(false);
  });
});
