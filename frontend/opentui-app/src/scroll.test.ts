import { describe, expect, test } from "bun:test";
import { CustomSpeedScroll, SCROLLBAR_TRACK, createScrollAcceleration } from "./scroll.ts";

describe("scroll OpenCode parity", () => {
  test("CustomSpeedScroll returns fixed speed", () => {
    const s = new CustomSpeedScroll(3);
    expect(s.tick()).toBe(3);
    expect(s.tick()).toBe(3);
  });

  test("createScrollAcceleration defaults to 3 lines/tick", () => {
    delete process.env.RXYCODE_SCROLL_ACCEL;
    const accel = createScrollAcceleration();
    expect(accel.tick()).toBe(3);
  });

  test("scrollbar track is muted gray (not brand pink)", () => {
    expect(SCROLLBAR_TRACK.foregroundColor).toBe("#555555");
    expect(SCROLLBAR_TRACK.backgroundColor).toBe("#111111");
    expect(SCROLLBAR_TRACK.foregroundColor).not.toBe("#FF69B4");
  });
});
