import { describe, expect, test } from "bun:test";
import {
  ProtocolClient,
  ProtocolRpcError,
  ProtocolTimeoutError,
} from "@rxycode/protocol-client";
import { StdioAppserverSession } from "./stdioTransport.ts";
import { statusFromModelsList } from "./stdioCommands.ts";

/** 2026-10-09 用户实测回归：服务端静默丢应答时，切换模型不得无限停在「正在切换…」。 */
describe("switchModel bounded waits", () => {
  test("models/set_active 无应答时按超时落成失败而不是永远转圈", async () => {
    // 真 ProtocolClient + writeLine 黑洞：服务器永远不应答。
    // DialogModel 的实际链路（sendCommand 的 model 分支）会 catch 后落成失败文案；
    // 这里直接取 switchModel 的拒绝面，断言其按超时收敛而非悬挂。
    const client = new ProtocolClient(() => {});
    const session = Object.create(StdioAppserverSession.prototype);
    session.ensureReady = async () => client;
    session.sessionId = null;

    const started = Date.now();
    let caught: unknown = null;
    try {
      await session.switchModel("some/model");
    } catch (e) {
      caught = e;
    }
    const elapsed = Date.now() - started;

    expect(caught).toBeTruthy();
    expect(String((caught as Error).message)).toContain("RPC timeout: models/set_active");
    // MODEL_SET_ACTIVE_TIMEOUT_MS = 10s；允许调度误差，但必须显著 < 60s。
    expect(elapsed).toBeLessThan(20_000);
  }, 25_000);

  test("session/set_model 超时明确失败：整体返回失败而非假成功", async () => {
    // 2026-10-11 假成功修复：全局 active 已切但 worker 还跑旧模型时必须返回失败。
    const calls: string[] = [];
    const client = {
      requestWithTimeout: (method: string) => {
        calls.push(method);
        return method === "session/set_model"
          ? Promise.reject(new ProtocolTimeoutError("session/set_model"))
          : Promise.resolve({ ok: true, id: "some/model" });
      },
    };
    let snapshotPolls = 0;
    const session = Object.create(StdioAppserverSession.prototype);
    session.ensureReady = async () => client;
    session.sessionId = "s-1";
    session.lastStatus = { model: "old/model" };
    session.fetchStatusSnapshot = async () => {
      snapshotPolls++;
      return null;
    };

    const result = await session.switchModel("some/model");
    expect(result.ok).toBe(false);
    expect(result.action).toBe("error");
    expect(String(result.error)).toContain("请重试");
    expect(String(result.error)).toContain("session/set_model");
    expect(calls).toEqual(["models/set_active", "session/set_model"]);
    // 失败路径不刷新状态快照：芯片继续显示 worker 实际在用的旧模型。
    expect(snapshotPolls).toBe(0);
    expect(session.lastStatus.model).toBe("old/model");
  });

  test("models/list 超时后 inflight 清掉，下一次可以重新请求", async () => {
    process.env.RXYCODE_ADMIN_RPC_TIMEOUT_MS = "40";
    let sends = 0;
    const client = new ProtocolClient(() => {
      sends += 1;
    });
    const session = Object.create(StdioAppserverSession.prototype) as StdioAppserverSession;
    session.ensureReady = async () => client;
    try {
      await expect(session.listModels()).rejects.toThrow(/RPC timeout: models\/list/);
      const afterFirst = sends;
      await expect(session.listModels()).rejects.toThrow(/RPC timeout: models\/list/);
      expect(sends).toBeGreaterThan(afterFirst);
    } finally {
      delete process.env.RXYCODE_ADMIN_RPC_TIMEOUT_MS;
    }
  });

  test("attachSession 失败不提交新 sessionId，后到的旧请求不覆盖新会话", async () => {
    const pending: Array<{
      method: string;
      resolve: (value: unknown) => void;
      reject: (err: unknown) => void;
    }> = [];
    const client = {
      requestWithTimeout: (method: string) =>
        new Promise((resolve, reject) => {
          pending.push({ method, resolve, reject });
        }),
    };
    const session = Object.create(StdioAppserverSession.prototype) as {
      ensureReady: () => Promise<typeof client>;
      sessionId: string | null;
      attachGeneration: number;
      interrupt: () => Promise<void>;
      forgetTodoView: () => void;
      refreshTodo: () => Promise<void>;
      warmBootstrap: () => Promise<void>;
      attachSession: (sessionId: string) => Promise<{ session_id: string; messages: unknown[] }>;
    };
    session.ensureReady = async () => client;
    session.sessionId = "old-session";
    session.attachGeneration = 0;
    session.interrupt = async () => {};
    session.forgetTodoView = () => {};
    session.refreshTodo = async () => {};
    session.warmBootstrap = async () => {};

    const failed = session.attachSession("session-a");
    await Promise.resolve();
    await Promise.resolve();
    expect(session.sessionId).toBe("old-session");
    const firstEvents = pending.filter((item) => item.method === "session/events");
    expect(firstEvents.length).toBe(1);
    firstEvents[0]!.reject(new Error("RPC timeout: session/events"));
    await expect(failed).rejects.toThrow(/session\/events/);
    expect(session.sessionId).toBe("old-session");

    const slow = session.attachSession("session-slow");
    const fast = session.attachSession("session-fast");
    await Promise.resolve();
    await Promise.resolve();
    const loads = pending.filter((item) => item.method === "session/events");
    const fastCall = loads[loads.length - 1]!;
    fastCall.resolve({ events: [{ method: "event/final", params: { text: "fast" } }] });
    const loaded = await fast;
    expect(loaded.session_id).toBe("session-fast");
    expect(session.sessionId).toBe("session-fast");
    await expect(slow).rejects.toThrow(/stale session attach/);
    expect(session.sessionId).toBe("session-fast");
  });

  test("失败切换后的 status 轮询仍显示 worker 模型，而不是新的全局默认", async () => {
    const client = {
      requestWithTimeout: (method: string) =>
        method === "session/set_model"
          ? Promise.reject(new Error("worker kept old"))
          : Promise.resolve({ ok: true, id: "new/model" }),
    };
    const session = Object.create(StdioAppserverSession.prototype) as {
      ensureReady: () => Promise<typeof client>;
      sessionId: string | null;
      lastStatus: { model?: string; context_max_k?: number } | null;
      sessionModelId: string | null;
      listModels: () => Promise<unknown>;
      switchModel: (id: string) => Promise<{ ok: boolean }>;
      fetchStatusSnapshot: () => Promise<{ model?: string; context_max_k?: number } | null>;
      attachSession: (sessionId: string, modelId?: string | null) => Promise<{ session_id: string }>;
      resetSession: () => void;
    };
    session.ensureReady = async () => client;
    session.sessionId = "s-1";
    session.lastStatus = { model: "old-model", context_max_k: 64 };
    session.sessionModelId = "old/model";
    const result = await session.switchModel("new/model");
    expect(result.ok).toBe(false);
    session.listModels = async () => ({
      active: "new/model",
      models: [
        { id: "old/model", name: "old-model", nickname: "old-model", active: false, context_window: 64000 },
        { id: "new/model", name: "new-model", nickname: "new-model", active: true, context_window: 128000 },
      ],
    });
    const status = await session.fetchStatusSnapshot();
    expect(status?.model).toBe("old-model");
    expect(status?.context_max_k).toBe(64);
    expect(session.sessionModelId).toBe("old/model");
  });

  test("失败切模的模型身份不串到下一会话，同名模型的名称和上下文来自同一条目", async () => {
    const client = {
      requestWithTimeout: async (method: string) => {
        if (method === "session/set_model") throw new Error("worker kept old");
        if (method === "session/events") return { events: [] };
        return { ok: true, id: "second/shared-name" };
      },
    };
    const session = Object.create(StdioAppserverSession.prototype) as {
      ensureReady: () => Promise<typeof client>;
      sessionId: string | null;
      sessionModelId: string | null;
      lastStatus: { model?: string; context_max_k?: number } | null;
      interrupt: () => Promise<void>;
      forgetTodoView: () => void;
      refreshTodo: () => Promise<void>;
      warmBootstrap: () => Promise<void>;
      listModels: () => Promise<unknown>;
      switchModel: (id: string) => Promise<{ ok: boolean }>;
      attachSession: (sessionId: string, modelId?: string | null) => Promise<unknown>;
      fetchStatusSnapshot: () => Promise<{ model?: string; context_max_k?: number } | null>;
      resetSession: () => void;
    };
    session.ensureReady = async () => client;
    session.interrupt = async () => {};
    session.forgetTodoView = () => {};
    session.refreshTodo = async () => {};
    session.warmBootstrap = async () => {};
    session.sessionId = "session-A";
    session.sessionModelId = "first/shared-name";
    session.lastStatus = { model: "shared-name · first.example", context_max_k: 64 };
    session.listModels = async () => ({
      active: "second/shared-name",
      models: [
        {
          id: "first/shared-name",
          name: "shared-name",
          nickname: "shared-name",
          base_url: "https://first.example/v1",
          context_window: 64000,
        },
        {
          id: "second/shared-name",
          name: "shared-name",
          nickname: "shared-name",
          base_url: "https://second.example/v1",
          context_window: 256000,
        },
      ],
    });
    const failed = await session.switchModel("second/shared-name");
    expect(failed.ok).toBe(false);
    const locked = await session.fetchStatusSnapshot();
    expect(locked?.model).toContain("first.example");
    expect(locked?.context_max_k).toBe(64);

    await session.attachSession("session-B", "second/shared-name");
    expect(session.sessionId).toBe("session-B");
    const next = await session.fetchStatusSnapshot();
    expect(next?.model).toContain("second.example");
    expect(next?.context_max_k).toBe(256);
    expect(session.sessionModelId).toBe("second/shared-name");

    const raw = session as unknown as {
      approvalTimers: Map<unknown, unknown>;
      pendingApprovals: Map<unknown, unknown>;
      pendingQuestions: Map<unknown, unknown>;
      client: null;
      proc: null;
    };
    raw.approvalTimers = new Map();
    raw.pendingApprovals = new Map();
    raw.pendingQuestions = new Map();
    raw.client = null;
    raw.proc = null;
    session.resetSession();
    expect(session.sessionModelId).toBeNull();
    expect(session.sessionId).toBeNull();
  });

  test("切模尚未返回时加载另一会话，set_model 仍发给原会话且不覆盖新模型", async () => {
    const pending: Array<{
      method: string;
      params: { session_id?: string; model_id?: string };
      resolve: (value: unknown) => void;
      reject: (err: unknown) => void;
    }> = [];
    const client = {
      requestWithTimeout: (method: string, params?: { session_id?: string; model_id?: string }) =>
        new Promise((resolve, reject) => {
          pending.push({ method, params: params ?? {}, resolve, reject });
        }),
    };
    const session = Object.create(StdioAppserverSession.prototype) as {
      ensureReady: () => Promise<typeof client>;
      sessionId: string | null;
      sessionModelId: string | null;
      attachGeneration: number;
      interrupt: () => Promise<void>;
      forgetTodoView: () => void;
      refreshTodo: () => Promise<void>;
      warmBootstrap: () => Promise<void>;
      listModels: () => Promise<unknown>;
      switchModel: (id: string) => Promise<{ ok: boolean }>;
      attachSession: (sessionId: string, modelId?: string | null) => Promise<unknown>;
      fetchStatusSnapshot: () => Promise<unknown>;
    };
    session.ensureReady = async () => client;
    session.interrupt = async () => {};
    session.forgetTodoView = () => {};
    session.refreshTodo = async () => {};
    session.warmBootstrap = async () => {};
    session.attachGeneration = 0;
    session.sessionId = "session-A";
    session.sessionModelId = "model-A";
    session.listModels = async () => ({
      active: "model-B",
      models: [
        { id: "model-A", name: "model-A", context_window: 64000 },
        { id: "model-B", name: "model-B", context_window: 128000 },
      ],
    });
    session.fetchStatusSnapshot = async () => ({ model: "model-B", context_max_k: 128 });

    const switching = session.switchModel("model-new");
    await Promise.resolve();
    const activeCall = pending.find((item) => item.method === "models/set_active");
    expect(activeCall).toBeTruthy();
    const attached = session.attachSession("session-B", "model-B");
    for (let i = 0; i < 8 && !pending.some((item) => item.method === "session/events"); i += 1) {
      await Promise.resolve();
    }
    const events = pending.find((item) => item.method === "session/events");
    expect(events).toBeTruthy();
    events!.resolve({ events: [] });
    await attached;
    expect(session.sessionId).toBe("session-B");
    expect(session.sessionModelId).toBe("model-B");

    activeCall!.resolve({ ok: true, id: "model-new" });
    for (let i = 0; i < 8 && !pending.some((item) => item.method === "session/set_model"); i += 1) {
      await Promise.resolve();
    }
    const setModel = pending.find((item) => item.method === "session/set_model");
    expect(setModel?.params.session_id).toBe("session-A");
    setModel!.resolve({ ok: true });
    await switching;
    expect(session.sessionId).toBe("session-B");
    expect(session.sessionModelId).toBe("model-B");

    const failed = session.switchModel("model-other");
    await Promise.resolve();
    const secondActive = pending.filter((item) => item.method === "models/set_active").at(-1)!;
    const back = session.attachSession("session-A", "model-A");
    for (let i = 0; i < 8 && pending.filter((item) => item.method === "session/events").length < 2; i += 1) {
      await Promise.resolve();
    }
    pending.filter((item) => item.method === "session/events").at(-1)!.resolve({ events: [] });
    await back;
    secondActive.resolve({ ok: true });
    for (let i = 0; i < 8 && pending.filter((item) => item.method === "session/set_model").length < 2; i += 1) {
      await Promise.resolve();
    }
    const lateSet = pending.filter((item) => item.method === "session/set_model").at(-1)!;
    expect(lateSet.params.session_id).toBe("session-B");
    lateSet.reject(new Error("worker kept old"));
    await failed;
    expect(session.sessionId).toBe("session-A");
    expect(session.sessionModelId).toBe("model-A");
  });

  test("状态刷新挂起时加载另一会话，旧切模不返回成功", async () => {
    const pending: Array<{
      method: string;
      params: { session_id?: string };
      resolve: (value: unknown) => void;
    }> = [];
    let releaseStatus: (() => void) | null = null;
    const client = {
      requestWithTimeout: (method: string, params?: { session_id?: string }) =>
        new Promise((resolve) => {
          pending.push({ method, params: params ?? {}, resolve });
        }),
    };
    const session = Object.create(StdioAppserverSession.prototype) as {
      ensureReady: () => Promise<typeof client>;
      sessionId: string | null;
      sessionModelId: string | null;
      attachGeneration: number;
      interrupt: () => Promise<void>;
      forgetTodoView: () => void;
      refreshTodo: () => Promise<void>;
      warmBootstrap: () => Promise<void>;
      switchModel: (id: string) => Promise<{ ok: boolean; action?: string; message?: string }>;
      attachSession: (sessionId: string, modelId?: string | null) => Promise<unknown>;
      fetchStatusSnapshot: () => Promise<unknown>;
    };
    session.ensureReady = async () => client;
    session.interrupt = async () => {};
    session.forgetTodoView = () => {};
    session.refreshTodo = async () => {};
    session.warmBootstrap = async () => {};
    session.attachGeneration = 0;
    session.sessionId = "session-A";
    session.sessionModelId = "model-A";
    session.fetchStatusSnapshot = () =>
      new Promise((resolve) => {
        releaseStatus = () => resolve({ model: "model-new", context_max_k: 8 });
      });

    const switching = session.switchModel("model-new");
    for (let i = 0; i < 8 && !pending.some((item) => item.method === "models/set_active"); i += 1) {
      await Promise.resolve();
    }
    pending.find((item) => item.method === "models/set_active")!.resolve({ ok: true });
    for (let i = 0; i < 8 && !pending.some((item) => item.method === "session/set_model"); i += 1) {
      await Promise.resolve();
    }
    const setModel = pending.find((item) => item.method === "session/set_model");
    expect(setModel?.params.session_id).toBe("session-A");
    setModel!.resolve({ ok: true });
    for (let i = 0; i < 8 && releaseStatus === null; i += 1) {
      await Promise.resolve();
    }
    expect(releaseStatus).toBeTruthy();

    const attached = session.attachSession("session-B", "model-B");
    for (let i = 0; i < 8 && !pending.some((item) => item.method === "session/events"); i += 1) {
      await Promise.resolve();
    }
    pending.find((item) => item.method === "session/events")!.resolve({ events: [] });
    await attached;
    expect(session.sessionModelId).toBe("model-B");

    releaseStatus!();
    const result = await switching;
    expect(result.ok).toBe(false);
    expect(result.action).not.toBe("model_changed");
    expect(result.message).toBe("会话已更换");
    expect(session.sessionId).toBe("session-B");
    expect(session.sessionModelId).toBe("model-B");
  });

  test("session/set_model RPC 报错同样返回失败（含错误原因）", async () => {
    const client = {
      requestWithTimeout: (method: string) =>
        method === "session/set_model"
          ? Promise.reject(new ProtocolRpcError({ code: -32603, message: "worker busy" }))
          : Promise.resolve({ ok: true, id: "some/model" }),
    };
    const session = Object.create(StdioAppserverSession.prototype);
    session.ensureReady = async () => client;
    session.sessionId = "s-1";
    session.fetchStatusSnapshot = async () => null;

    const result = await session.switchModel("some/model");
    expect(result.ok).toBe(false);
    expect(result.action).toBe("error");
    expect(String(result.error)).toContain("worker busy");
    expect(String(result.error)).toContain("请重试");
  });

  test("没有打开的 session 时跳过 session/set_model，仍按成功返回", async () => {
    // 兼容路径：全局默认模型已持久化切换，worker 绑定本就该跳过 ②。
    const calls: string[] = [];
    const client = {
      requestWithTimeout: (method: string) => {
        calls.push(method);
        return Promise.resolve({ ok: true, id: "some/model" });
      },
    };
    const session = Object.create(StdioAppserverSession.prototype);
    session.ensureReady = async () => client;
    session.sessionId = null;
    session.fetchStatusSnapshot = async () => null;

    const result = await session.switchModel("some/model");
    expect(result.ok).toBe(true);
    expect(result.action).toBe("model_changed");
    expect(calls).toEqual(["models/set_active"]);
  });

  test("status snapshot 卡住时也会被 bounded wait 兜底", async () => {
    const client = {
      requestWithTimeout: () => Promise.resolve({ ok: true, id: "some/model" }),
    };
    const session = Object.create(StdioAppserverSession.prototype);
    session.ensureReady = async () => client;
    session.sessionId = null;
    session.fetchStatusSnapshot = () => new Promise(() => {});
    session.lastStatus = { model: "old/model" };

    const started = Date.now();
    const result = await session.switchModel("some/model");
    const elapsed = Date.now() - started;

    expect(result.ok).toBe(true);
    // 快照失败语义本就写入新 id（this.lastStatus = {...prev, model: modelId}）。
    expect(session.lastStatus.model).toBe("some/model");
    expect(elapsed).toBeLessThan(15_000);
  }, 20_000);
});
