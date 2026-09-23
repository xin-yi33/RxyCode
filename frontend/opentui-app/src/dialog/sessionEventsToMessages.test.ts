import { describe, expect, test } from "bun:test";
import { normalizeLoadedMessages, sessionEventsToMessages } from "./sessionEventsToMessages.ts";

describe("sessionEventsToMessages", () => {
  test("settles unmatched tools and restores thought plus markdown-ready assistant", () => {
    const messages = sessionEventsToMessages([
      { method: "session/prompt", params: { text: "修登录" }, ts: "2026-09-20T08:00:00Z" },
      {
        method: "event/tool_begin",
        params: { call_id: "c1", tool_name: "read", arguments: { path: "a.ts" } },
        ts: "2026-09-20T08:00:01Z",
      },
      {
        method: "event/tool_end",
        params: { call_id: "c1", ok: true, summary: "ok" },
        ts: "2026-09-20T08:00:02Z",
      },
      {
        method: "event/tool_begin",
        params: { call_id: "c2", tool_name: "bash", arguments: { command: "ls" } },
        ts: "2026-09-20T08:00:03Z",
      },
      {
        method: "event/final",
        params: { text: "**done**", thinking: "先读文件再改" },
        ts: "2026-09-20T08:00:04Z",
      },
    ]);
    const roles = messages.map((m) => m.role);
    expect(roles).toEqual(["user", "tool", "tool", "thinking", "assistant"]);
    expect(messages[1]?.toolStatus).toBe("success");
    expect(messages[1]?.toolArgs).toContain("a.ts");
    expect(messages[1]?.endedAt).toBeGreaterThan(0);
    expect(messages[2]?.toolStatus).toBe("cancelled");
    expect(messages[3]?.content).toBe("先读文件再改");
    expect(messages[4]?.content).toBe("**done**");
    expect(messages[4]?.done).toBe(true);
  });

  test("normalizeLoadedMessages keeps tool status and assistant done", () => {
    const replayed = sessionEventsToMessages([
      { method: "session/prompt", params: { text: "hi" } },
      { method: "event/tool_begin", params: { call_id: "x", tool_name: "read", arguments: { path: "a" } } },
      { method: "event/tool_end", params: { call_id: "x", ok: true, summary: "ok" } },
      { method: "event/final", params: { text: "# Hello" } },
    ]);
    const loaded = normalizeLoadedMessages(replayed);
    const tool = loaded.find((m) => m.role === "tool");
    expect(tool?.toolStatus).toBe("success");
    expect(tool?.toolArgs).toContain("a");
    expect(loaded.find((m) => m.role === "assistant")?.done).toBe(true);
    expect(loaded.find((m) => m.role === "assistant")?.content).toBe("# Hello");
  });

  test("matched tool_end error is settled with endedAt", () => {
    const messages = sessionEventsToMessages([
      {
        method: "event/tool_begin",
        params: { call_id: "e1", tool_name: "bash", arguments: { command: "bad" } },
      },
      {
        method: "event/tool_end",
        params: { call_id: "e1", ok: false, summary: "fail" },
      },
    ]);
    expect(messages[0]?.toolStatus).toBe("error");
    expect(messages[0]?.toolArgs).toContain("bad");
    expect(messages[0]?.endedAt).toBeGreaterThan(0);
  });

  test("normalizeLoadedMessages settles running tools and keeps error plus toolArgs", () => {
    const loaded = normalizeLoadedMessages([
      {
        role: "tool",
        content: "",
        toolStatus: "running",
        toolArgs: '{"path":"a.ts"}',
        toolName: "read",
      },
      {
        role: "tool",
        content: "boom",
        toolStatus: "error",
        toolArgs: '{"cmd":"x"}',
        toolName: "bash",
      },
      { role: "assistant", content: "**x**", done: true },
    ]);
    expect(loaded[0]?.toolStatus).not.toBe("running");
    expect(loaded[0]?.toolArgs).toContain("a.ts");
    expect(loaded[1]?.toolStatus).toBe("error");
    expect(loaded[1]?.toolArgs).toContain("cmd");
    expect(loaded[2]?.done).toBe(true);
  });
});
