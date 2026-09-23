import { describe, expect, test } from "bun:test";
import { liveProgressText, notifyToStreamEvent } from "./notifyToStreamEvent.ts";

describe("notifyToStreamEvent", () => {
  test("maps message_delta to token", () => {
    expect(
      notifyToStreamEvent("event/message_delta", { session_id: "s1", text: "hi" }),
    ).toEqual({ type: "token", text: "hi", intermediate: false });
  });

  test("maps intermediate flag through token/progress/reasoning (2026-09-23 P0)", () => {
    // 子代理（intermediate=true）的流式事件必须把标记透传到 StreamEvent，
    // streamReducer 据此把它们挡在主聊流外。
    expect(
      notifyToStreamEvent("event/message_delta", { session_id: "s1", text: "hi", intermediate: true }),
    ).toEqual({ type: "token", text: "hi", intermediate: true });
    expect(
      notifyToStreamEvent("event/progress", { session_id: "s1", text: "p", intermediate: true }),
    ).toEqual({ type: "progress", message: "p", text: "p", intermediate: true });
    expect(
      notifyToStreamEvent("event/reasoning_snapshot", { session_id: "s1", text: "t", snapshot: false, intermediate: true }),
    ).toEqual({ type: "reasoning", thinking: "t", snapshot: false, intermediate: true });
  });

  test("maps tool_begin and tool_end", () => {
    expect(
      notifyToStreamEvent("event/tool_begin", {
        session_id: "s1",
        call_id: "c1",
        tool_name: "read_file",
        arguments: { path: "a.ts" },
      }),
    ).toEqual({
      type: "tool_call",
      name: "read_file",
      call_id: "c1",
      args: { path: "a.ts" },
    });
    expect(
      notifyToStreamEvent("event/tool_end", {
        session_id: "s1",
        call_id: "c1",
        ok: true,
        summary: "done",
      }),
    ).toEqual({
      type: "tool_result",
      name: "",
      call_id: "c1",
      result: "done",
      status: "success",
    });
  });

  test("maps event/final token fields for the status bar", () => {
    expect(
      notifyToStreamEvent("event/final", {
        session_id: "s1",
        run_id: "r1",
        text: "done",
        input_tokens: 900,
        output_tokens: 100,
        cache_hit_tokens: 400,
        cache_hit_rate: 44.4,
        reporting_status: "reported",
      }),
    ).toEqual({
      type: "final",
      text: "done",
      message: "done",
      input_tokens: 900,
      output_tokens: 100,
      cache_hit_tokens: 400,
      cache_hit_rate: 44.4,
      reporting_status: "reported",
    });
  });

  test("maps event/token_usage for the status bar", () => {
    expect(
      notifyToStreamEvent("event/token_usage", {
        session_id: "s1",
        input_tokens: 1200,
        output_tokens: 300,
        cache_hit_tokens: 800,
        cache_hit_rate: 66.7,
        reporting_status: "reported",
      }),
    ).toEqual({
      type: "token_usage",
      input_tokens: 1200,
      output_tokens: 300,
      cache_hit_tokens: 800,
      cache_hit_rate: 66.7,
      reporting_status: "reported",
    });
  });

  test("maps event/plan to a plan document event", () => {
    expect(
      notifyToStreamEvent("event/plan", {
        session_id: "s1",
        steps: ["# Title", "## Steps", "1. inspect"],
      }),
    ).toEqual({
      type: "plan",
      steps: ["# Title", "## Steps", "1. inspect"],
      text: "# Title\n## Steps\n1. inspect",
      message: "# Title\n## Steps\n1. inspect",
    });
  });

  test("maps event/team to a current-role progress line", () => {
    expect(
      notifyToStreamEvent("event/team", {
        session_id: "s1",
        role: "architect",
        stage: "plan",
        phase: "stage_started",
      }),
    ).toEqual({
      type: "progress",
      message: "[architect] plan",
      text: "[architect] plan",
    });
  });

  test("returns null for unknown methods", () => {
    expect(notifyToStreamEvent("event/server_heartbeat", {})).toBeNull();
  });

  test("liveProgressText ignores routing labels and keeps later stages", () => {
    expect(
      liveProgressText({ type: "progress", message: "mode=solo default heuristic" }),
    ).toBeNull();
    expect(liveProgressText({ type: "progress", message: "正在连接模型…" })).toBe(
      "等待模型返回…",
    );
    expect(liveProgressText({ type: "progress", message: "等待模型返回…" })).toBe(
      "等待模型返回…",
    );
    expect(liveProgressText({ type: "tool_call", name: "final_answer" })).toBeNull();
    expect(liveProgressText({ type: "tool_call", name: "write" })).toBe(
      "等待工具 write 返回…",
    );
    expect(liveProgressText({ type: "tool_call", name: "bash" })).toBe("等待终端返回…");
    expect(liveProgressText({ type: "tool_call", name: "vision" })).toBe(
      "等待视觉识别返回…",
    );
    expect(liveProgressText({ type: "reasoning", thinking: "思考中..." })).toBe("思考中…");
    expect(liveProgressText({ type: "reasoning", thinking: "The user" })).toBe("思考中…");
    expect(liveProgressText({ type: "progress", message: "模型输出中…" })).toBeNull();
    expect(liveProgressText({ type: "progress", message: "Generating... (50 chars)" })).toBeNull();
    expect(
      liveProgressText({ type: "progress", message: "正在等待模型响应…" }),
    ).toBeNull();
    expect(
      liveProgressText({ type: "progress", message: "Waiting for model response…" }),
    ).toBeNull();
  });
});
