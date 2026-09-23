import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  formatElapsedSuffix,
  formatMessageLine,
  formatHeaderLine,
  formatInputHint,
  shouldRenderThought,
} from "./format.ts";
import { thoughtShowsBody } from "./lib/thinkingDisplay.ts";
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
      "RxyCode v1.4.0 · build · deepseek-v4-flash",
    );
    expect(formatHeaderLine("plan", "m", true)).toContain("思考中");
  });

  test("formatHeaderLine keeps the locked 3-arg signature", () => {
    const src = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "format.ts"),
      "utf8",
    );
    expect(src).toMatch(/export function formatHeaderLine\(mode: Mode, model: string, thinkingLive: boolean\)/);
    expect(src).toMatch(/废弃代码（2026-09-21）：formatHeaderLine 曾作为顶栏唯一文案/);
  });

  test("input hint shows queue affordance while processing", () => {
    expect(formatInputHint(false)).toBe("Ready");
    expect(formatInputHint(true)).toBe("思考中");
    expect(formatInputHint(true, 2)).toBe("思考中 · 队列 2");
    expect(formatInputHint(false, 1)).toBe("Ready · 队列 1");
  });

  // 2026-09-23: 本地滴答的已运行秒数后缀——后端心跳停摆时状态行仍每秒
  // 变化（用户报告：log 在跑，TUI 不像在跑）。
  test("formatElapsedSuffix ticks locally and degrades to empty", () => {
    expect(formatElapsedSuffix(null)).toBe("");
    expect(formatElapsedSuffix(-3)).toBe("");
    expect(formatElapsedSuffix(Number.NaN)).toBe("");
    expect(formatElapsedSuffix(0)).toBe(" · 0s");
    expect(formatElapsedSuffix(5.9)).toBe(" · 5s");
    expect(formatElapsedSuffix(59)).toBe(" · 59s");
    expect(formatElapsedSuffix(60)).toBe(" · 1m0s");
    expect(formatElapsedSuffix(331)).toBe(" · 5m31s");
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

  test("settled empty Thought is hidden; a real chain stays", () => {
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

  test("live Thought shows body even when /thinking is collapsed", () => {
    expect(thoughtShowsBody({ expanded: false, done: false })).toBe(true);
    expect(thoughtShowsBody({ expanded: false, done: true })).toBe(false);
    expect(thoughtShowsBody({ expanded: true, done: true })).toBe(true);
  });
});
