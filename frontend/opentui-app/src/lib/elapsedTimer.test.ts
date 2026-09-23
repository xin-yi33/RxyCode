import { describe, expect, test } from "bun:test";
import { ElapsedTimer, formatElapsed } from "./elapsedTimer.ts";

describe("ElapsedTimer", () => {
  test("formats ms under one second", () => {
    expect(formatElapsed(373)).toBe("373ms");
    expect(new ElapsedTimer(0).format(0)).toBe("0ms");
  });

  test("formats tenths of a second below 60s", () => {
    expect(formatElapsed(1200)).toBe("1.2s");
    expect(formatElapsed(12340)).toBe("12.3s");
  });

  test("formats minutes then hours", () => {
    expect(formatElapsed(61_000)).toBe("1 min 1 s");
    expect(formatElapsed(3_600_000)).toBe("1 h 0 min");
    expect(formatElapsed(3_721_000)).toBe("1 h 2 min");
  });
});
