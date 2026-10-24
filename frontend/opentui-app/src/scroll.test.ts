import { describe, expect, test } from "bun:test";
import { CustomSpeedScroll, SCROLLBAR_TRACK, createScrollAcceleration } from "./scroll.ts";
import { SURFACES, isPureBlack } from "./theme.ts";

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
    // 2026-10-24 UI polish: track comes from the surface token (near-black, not #000).
    expect(SCROLLBAR_TRACK.backgroundColor).toBe(SURFACES.track);
    expect(isPureBlack(SCROLLBAR_TRACK.backgroundColor)).toBe(false);
    expect(SCROLLBAR_TRACK.foregroundColor).not.toBe("#FF69B4");
  });
});
