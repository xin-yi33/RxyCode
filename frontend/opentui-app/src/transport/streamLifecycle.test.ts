import { describe, expect, test } from "bun:test";
import { shouldClearStreamingOnNotify } from "./streamLifecycle.ts";

describe("shouldClearStreamingOnNotify", () => {
  test("final/done/error end Processing without waiting for RPC", () => {
    expect(shouldClearStreamingOnNotify("event/final")).toBe(true);
    expect(shouldClearStreamingOnNotify("event/done")).toBe(true);
    expect(shouldClearStreamingOnNotify("event/error")).toBe(true);
  });

  test("mid-stream events keep Processing", () => {
    expect(shouldClearStreamingOnNotify("event/message_delta")).toBe(false);
    expect(shouldClearStreamingOnNotify("event/reasoning_snapshot")).toBe(false);
    expect(shouldClearStreamingOnNotify("event/tool_begin")).toBe(false);
    expect(shouldClearStreamingOnNotify("event/progress")).toBe(false);
  });
});
