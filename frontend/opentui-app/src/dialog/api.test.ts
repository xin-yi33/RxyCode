import { describe, expect, test } from "bun:test";
import { listFromCommandResult } from "./api.ts";

describe("listFromCommandResult", () => {
  test("parses chats for session", () => {
    const items = listFromCommandResult(
      { chats: [{ name: "a", preview: "hi", time: "today" }] },
      "session",
    );
    expect(items).toEqual([{ id: "a", title: "a", description: "today" }]);
  });

  test("parses memories", () => {
    const items = listFromCommandResult(
      { memories: [{ id: 1, text: "note" }] },
      "memory",
    );
    expect(items[0]?.title).toBe("[1]");
    expect(items[0]?.description).toBe("note");
  });

  test("parses mcp servers", () => {
    const items = listFromCommandResult(
      { servers: [{ name: "fs", command: "npx x" }] },
      "mcp",
    );
    expect(items[0]).toEqual({ id: "fs", title: "fs", description: "npx x" });
  });
});
