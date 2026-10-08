import { describe, expect, test } from "bun:test";
import { StdioAppserverSession } from "./stdioTransport.ts";
import type { TodoDockSnapshot } from "../todoDock.ts";

function harness(sessionId = "sess-a") {
  const seen: TodoDockSnapshot[] = [];
  const session = new StdioAppserverSession();
  const raw = session as unknown as {
    sessionId: string | null;
    client: {
      request: (method: string, params: unknown) => Promise<unknown>;
      rejectAllPending: (err?: Error) => void;
    } | null;
    proc: { exitCode: number | null; kill: () => void; exited: Promise<number> } | null;
    ready: Promise<void> | null;
    todoTicket: number;
    forgetTodoView: () => void;
    resetSession: (reason?: Error) => void;
  };
  raw.sessionId = sessionId;
  session.onTodo = (snapshot) => {
    seen.push(snapshot);
  };
  return { session, raw, seen };
}

function stubAlive(
  raw: ReturnType<typeof harness>["raw"],
  request: (method: string, params: unknown) => Promise<unknown>,
) {
  raw.client = { request, rejectAllPending: () => {} };
  raw.proc = { exitCode: null, kill() {}, exited: new Promise(() => {}) };
  raw.ready = Promise.resolve();
}

describe("stdio todo dock transport", () => {
  test("an older revision does not replace the current list", () => {
    const { session, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 5,
      items: [{ id: "t1", content: "新", status: "in_progress" }],
    });
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 2,
      items: [{ id: "t1", content: "旧", status: "pending" }],
    });
    expect(seen.at(-1)?.revision).toBe(5);
    expect(seen.at(-1)?.items[0]?.content).toBe("新");
  });

  test("another session does not overwrite the dock", () => {
    const { session, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 1,
      items: [{ id: "t1", content: "这里", status: "pending" }],
    });
    session.publishTodo({
      session_id: "sess-b",
      list_id: "default",
      revision: 9,
      items: [{ id: "t9", content: "别处", status: "in_progress" }],
    });
    expect(seen).toHaveLength(1);
    expect(seen[0]?.items[0]?.content).toBe("这里");
  });

  test("a late todo/get from the previous session is dropped", async () => {
    const { session, raw, seen } = harness();
    let release: (value: unknown) => void = () => {};
    raw.client = {
      request: () =>
        new Promise((resolve) => {
          release = resolve;
        }),
      rejectAllPending: () => {},
    };
    const pending = session.refreshTodo();
    raw.sessionId = "sess-b";
    raw.todoTicket += 1;
    release({
      session_id: "sess-a",
      list_id: "default",
      revision: 4,
      items: [{ id: "a", content: "迟到", status: "pending" }],
    });
    await pending;
    expect(seen.some((snapshot) => snapshot.items.some((item) => item.content === "迟到"))).toBe(false);
  });

  test("session switch clears the previous projection", () => {
    const { session, raw, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 3,
      items: [{ id: "t1", content: "旧会话", status: "in_progress" }],
    });
    raw.forgetTodoView();
    expect(seen.at(-1)?.items).toEqual([]);
    expect(seen.at(-1)?.revision).toBe(0);
  });

  test("attachSession loads the new session and ignores the old one", async () => {
    const { session, raw, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 3,
      items: [{ id: "t1", content: "旧会话", status: "in_progress" }],
    });
    stubAlive(raw, async (method) => {
      if (method === "todo/get") {
        return {
          session_id: "sess-b",
          list_id: "default",
          revision: 1,
          items: [{ id: "b", content: "新会话", status: "pending" }],
        };
      }
      if (method === "session/events") return { events: [] };
      return {};
    });
    await session.attachSession("sess-b");
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 9,
      items: [{ id: "a", content: "迟到旧会话", status: "in_progress" }],
    });
    expect(seen.at(-1)?.items[0]?.content).toBe("新会话");
    expect(seen.at(-1)?.revision).toBe(1);
  });

  test("trashing the active session loads the replacement list", async () => {
    const { session, raw, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 4,
      items: [{ id: "t1", content: "将被删除", status: "pending" }],
    });
    stubAlive(raw, async (method) => {
      if (method === "session/new") return { session_id: "sess-new" };
      if (method === "todo/get") {
        return {
          session_id: "sess-new",
          list_id: "default",
          revision: 2,
          items: [{ id: "n", content: "新清单", status: "in_progress" }],
        };
      }
      return {};
    });
    await session.trashSession("sess-a");
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 8,
      items: [{ id: "a", content: "旧清单迟到", status: "pending" }],
    });
    expect(seen.at(-1)?.items[0]?.content).toBe("新清单");
    expect(seen.at(-1)?.revision).toBe(2);
  });

  test("resetSession clears the dock and drops a late snapshot", () => {
    const { session, raw, seen } = harness();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 2,
      items: [{ id: "t1", content: "重置前", status: "pending" }],
    });
    raw.resetSession();
    session.publishTodo({
      session_id: "sess-a",
      list_id: "default",
      revision: 9,
      items: [{ id: "a", content: "重置后迟到", status: "in_progress" }],
    });
    expect(seen.at(-1)?.items).toEqual([]);
    expect(seen.at(-1)?.revision).toBe(0);
  });
});
