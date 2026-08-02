import { describe, expect, test } from "bun:test";
import { notifyToStreamEvent } from "./notifyToStreamEvent.ts";

describe("notifyToStreamEvent", () => {
  test("maps message_delta to token", () => {
    expect(
      notifyToStreamEvent("event/message_delta", { session_id: "s1", text: "hi" }),
    ).toEqual({ type: "token", text: "hi" });
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
      result: "done",
      status: "success",
    });
  });

  test("returns null for unknown methods", () => {
    expect(notifyToStreamEvent("event/server_heartbeat", {})).toBeNull();
  });
});
