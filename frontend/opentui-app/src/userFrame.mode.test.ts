import { describe, expect, test } from "bun:test";
import { MODE_COLORS, type ChatMessage, type Mode } from "./types.ts";

/** Mirror ChatLine user-frame color resolution (stamped mode wins). */
export function resolveUserFrameColor(
  msg: Pick<ChatMessage, "mode">,
  liveMode: Mode,
): string {
  if (msg.mode && MODE_COLORS[msg.mode]) return MODE_COLORS[msg.mode];
  return MODE_COLORS[liveMode];
}

describe("user frame color stamps send-time mode", () => {
  test("build message stays pink after live mode switches to plan", () => {
    const msg: ChatMessage = {
      id: "u1",
      role: "user",
      content: "hello",
      timestamp: 1,
      mode: "build",
    };
    expect(resolveUserFrameColor(msg, "plan")).toBe(MODE_COLORS.build);
    expect(resolveUserFrameColor(msg, "plan")).not.toBe(MODE_COLORS.plan);
  });

  test("missing stamp falls back to live mode", () => {
    const msg: ChatMessage = {
      id: "u2",
      role: "user",
      content: "old",
      timestamp: 1,
    };
    expect(resolveUserFrameColor(msg, "plan")).toBe(MODE_COLORS.plan);
  });
});
