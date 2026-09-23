import { describe, expect, test } from "bun:test";
import {
  composeTurnWithSteers,
  raceWithAbort,
  shouldClearStreamingOnNotify,
  shouldClearStreamingOnUserCancel,
  spliceTurnMessages,
} from "./streamLifecycle.ts";
import type { ChatMessage } from "../types.ts";

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

  test("user Esc cancel leaves Processing without waiting for session/prompt", () => {
    expect(shouldClearStreamingOnUserCancel()).toBe(true);
  });
});

describe("raceWithAbort", () => {
  test("already-aborted signal rejects without waiting for the request", async () => {
    const controller = new AbortController();
    controller.abort();
    const hung = new Promise<string>(() => {});
    await expect(raceWithAbort(hung, controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  test("abort while waiting rejects before the request resolves", async () => {
    const controller = new AbortController();
    const hung = new Promise<string>(() => {});
    const raced = raceWithAbort(hung, controller.signal);
    controller.abort();
    await expect(raced).rejects.toMatchObject({ name: "AbortError" });
  });

  test("returns the request value when not aborted", async () => {
    expect(await raceWithAbort(Promise.resolve("ok"))).toBe("ok");
  });
});

const user = (id: string, content: string): ChatMessage => ({
  id,
  role: "user",
  content,
  timestamp: 1,
});
const assistant = (id: string, content: string): ChatMessage => ({
  id,
  role: "assistant",
  content,
  timestamp: 1,
});

describe("spliceTurnMessages", () => {
  test("keeps a later queued user bubble when the earlier turn republishes", () => {
    const prev = [
      user("u1", "先做这个"),
      assistant("a1", "好"),
      user("u2", "？"),
      assistant("a2", "第二轮"),
    ];
    const next = spliceTurnMessages(prev, "u1", [assistant("a1b", "第一轮更新")]);
    expect(next.map((m) => m.id)).toEqual(["u1", "a1b", "u2", "a2"]);
    expect(next.find((m) => m.id === "u2")?.content).toBe("？");
  });

  test("ignores a stale turn whose user row was already dropped", () => {
    const prev = [user("u2", "？"), assistant("a2", "hi")];
    expect(spliceTurnMessages(prev, "u1", [assistant("ghost", "旧回合")])).toEqual(prev);
  });
});

describe("composeTurnWithSteers", () => {
  test("later stream rows appear after the steered user bubble", () => {
    const thinking: ChatMessage = { id: "t1", role: "thinking", content: "…", timestamp: 1 };
    const toolA: ChatMessage = { id: "tool-a", role: "tool", content: "a", timestamp: 1 };
    const toolB: ChatMessage = { id: "tool-b", role: "tool", content: "b", timestamp: 1 };
    const steered = user("u-steer", "不是图标是图表");
    const composed = composeTurnWithSteers([thinking, toolA, toolB], [{ at: 2, msg: steered }]);
    expect(composed.map((m) => m.id)).toEqual(["t1", "tool-a", "u-steer", "tool-b"]);
  });

  test("republish does not pin a mid-turn steer user at the bottom", () => {
    const thinking: ChatMessage = { id: "t1", role: "thinking", content: "…", timestamp: 1 };
    const toolA: ChatMessage = { id: "tool-a", role: "tool", content: "a", timestamp: 1 };
    const toolB: ChatMessage = { id: "tool-b", role: "tool", content: "b", timestamp: 1 };
    const steered = user("u-steer", "不是图标是图表");
    const prev = [user("u1", "先做这个"), thinking, toolA, steered];
    const next = spliceTurnMessages(
      prev,
      "u1",
      composeTurnWithSteers([thinking, toolA, toolB], [{ at: 2, msg: steered }]),
    );
    expect(next.map((m) => m.id)).toEqual(["u1", "t1", "tool-a", "u-steer", "tool-b"]);
  });
});
