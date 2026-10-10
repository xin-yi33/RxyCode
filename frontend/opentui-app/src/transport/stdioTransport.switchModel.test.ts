import { describe, expect, test } from "bun:test";
import {
  ProtocolClient,
  ProtocolRpcError,
  ProtocolTimeoutError,
} from "@rxycode/protocol-client";
import { StdioAppserverSession } from "./stdioTransport.ts";

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
