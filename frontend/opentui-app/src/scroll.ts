import { MacOSScrollAccel, type ScrollAcceleration } from "@opentui/core";

/** OpenCode default: fixed 3 lines per wheel tick when accel is off. */
export class CustomSpeedScroll implements ScrollAcceleration {
  constructor(private speed: number) {}

  tick(_now?: number): number {
    return this.speed;
  }

  reset(): void {}
}

/**
 * Match OpenCode default (`getScrollAcceleration`): CustomSpeedScroll(3).
 * Set RXYCODE_SCROLL_ACCEL=1 to enable MacOSScrollAccel.
 */
export function createScrollAcceleration(): ScrollAcceleration {
  if (process.env.RXYCODE_SCROLL_ACCEL === "1") {
    return new MacOSScrollAccel();
  }
  return new CustomSpeedScroll(3);
}

/** OpenCode-style scrollbar track (muted border on dark field — not brand pink). */
export const SCROLLBAR_TRACK = {
  backgroundColor: "#111111",
  foregroundColor: "#555555",
} as const;
