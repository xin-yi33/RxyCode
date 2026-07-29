import { describe, expect, test } from "bun:test";
import { formatMessageLine, formatHeaderLine, formatInputHint } from "./format.ts";
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
      "RxyCode v1.2.2 · build · deepseek-v4-flash",
    );
    expect(formatHeaderLine("plan", "m", true)).toContain("思考中");
  });

  test("input hint shows Ready/Processing", () => {
    expect(formatInputHint(false)).toBe("Ready");
    expect(formatInputHint(true)).toBe("Processing...");
  });
});
