import { describe, expect, test } from "bun:test";
import {
  formatMessageLine,
  formatHeaderLine,
  formatInputHint,
  shouldRenderThought,
} from "./format.ts";
import type { ChatMessage } from "./types.ts";

describe("message formatting", () => {
  test("formats user/assistant/thinking/tool/system lines", () => {
    const cases: Array<[ChatMessage, string]> = [
      [{ id: "1", role: "user", content: "hello", timestamp: 1 }, "> hello"],
      [{ id: "2", role: "assistant", content: "world", timestamp: 1 }, "world"],
      [{ id: "3", role: "thinking", content: "ponder", timestamp: 1 }, "思考: ponder"],
      [
        { id: "4", role: "tool", content: "ok", timestamp: 1, toolName: "read", toolStatus: "success" },
        "⚙ read [success]",
      ],
      [{ id: "5", role: "system", content: "cleared", timestamp: 1 }, "• cleared"],
    ];
    for (const [msg, expected] of cases) {
      expect(formatMessageLine(msg)).toBe(expected);
    }
  });

  test("header keeps pink brand fields", () => {
    expect(formatHeaderLine("build", "deepseek-v4-flash", false)).toBe(
      "RxyCode v1.3.0 · build · deepseek-v4-flash",
    );
    expect(formatHeaderLine("plan", "m", true)).toContain("思考中");
  });

  test("input hint shows Ready/Processing", () => {
    expect(formatInputHint(false)).toBe("Ready");
    expect(formatInputHint(true)).toBe("Processing...");
  });

  test("live placeholder Thought stays visible while the run is in flight", () => {
    expect(
      shouldRenderThought({
        id: "t1",
        role: "thinking",
        content: "…",
        timestamp: 1,
        live: true,
        done: false,
      }),
    ).toBe(true);
    expect(
      shouldRenderThought({
        id: "t2",
        role: "thinking",
        content: "思考中...",
        timestamp: 1,
        done: false,
      }),
    ).toBe(true);
  });

  test("settled empty Thought is hidden; real reasoning stays", () => {
    expect(
      shouldRenderThought({
        id: "t3",
        role: "thinking",
        content: "…",
        timestamp: 1,
        done: true,
        live: false,
      }),
    ).toBe(false);
    expect(
      shouldRenderThought({
        id: "t4",
        role: "thinking",
        content: "先看路由再回",
        timestamp: 1,
        done: false,
      }),
    ).toBe(true);
  });
});
