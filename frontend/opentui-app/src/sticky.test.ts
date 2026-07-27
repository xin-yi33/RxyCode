import { describe, expect, test } from "bun:test";
import {
  createStickyState,
  onSendMessage,
  onScrollToBottom,
  onUserScrollUp,
  shouldAutoStick,
} from "./sticky.ts";

describe("sticky scroll helpers", () => {
  test("starts sticky near bottom", () => {
    const state = createStickyState();
    expect(state.sticky).toBe(true);
    expect(state.userScrolledUp).toBe(false);
    expect(shouldAutoStick(state)).toBe(true);
  });

  test("user scroll up disables sticky", () => {
    const state = onUserScrollUp(createStickyState());
    expect(state.sticky).toBe(false);
    expect(state.userScrolledUp).toBe(true);
    expect(shouldAutoStick(state)).toBe(false);
  });

  test("send re-enables sticky", () => {
    const scrolled = onUserScrollUp(createStickyState());
    const afterSend = onSendMessage(scrolled);
    expect(afterSend.sticky).toBe(true);
    expect(afterSend.userScrolledUp).toBe(false);
    expect(shouldAutoStick(afterSend)).toBe(true);
  });

  test("scroll-to-bottom re-enables sticky", () => {
    const scrolled = onUserScrollUp(createStickyState());
    const afterBottom = onScrollToBottom(scrolled);
    expect(afterBottom.sticky).toBe(true);
    expect(afterBottom.userScrolledUp).toBe(false);
  });
});
