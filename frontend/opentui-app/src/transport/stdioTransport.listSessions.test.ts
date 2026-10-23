import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "bun:test";
import { ProtocolClient } from "@rxycode/protocol-client";
import { StdioAppserverSession } from "./stdioTransport.ts";

/** 2026-10-11 /session 打开慢：sessions/list 必须有界等待，而不是无限转圈。 */
describe("listSessions bounded wait", () => {
  test("sessions/list 无应答时按客户端超时落成错误，且不触发 respawn 重试", async () => {
    // 真 ProtocolClient + writeLine 黑洞：服务器永远不应答。
    const client = new ProtocolClient(() => {});
    const session = Object.create(StdioAppserverSession.prototype);
    let readyCalls = 0;
    let respawns = 0;
    session.ensureReady = async () => {
      readyCalls++;
      return client;
    };
    session.resetSession = () => {
      respawns++;
    };

    // 注入更小的 timeout，避免真等默认的 8s。
    const started = Date.now();
    let caught: unknown = null;
    try {
      await session.listSessions(80);
    } catch (e) {
      caught = e;
    }
    const elapsed = Date.now() - started;

    expect(caught).toBeTruthy();
    expect(String((caught as Error).message)).toContain("RPC timeout: sessions/list");
    expect(elapsed).toBeLessThan(5_000);
    // 超时不是「appserver 已死」：不 reset、不重发第二次请求。
    expect(respawns).toBe(0);
    expect(readyCalls).toBe(1);
  });

  test("默认超时为 8s 且 sessions/list 走 requestWithTimeout", () => {
    const src = readFileSync(resolve(__dirname, "stdioTransport.ts"), "utf8");
    expect(src).toMatch(/SESSIONS_LIST_TIMEOUT_MS = 8_000/);
    const section = src.slice(src.indexOf("requestSessionList"));
    expect(section.slice(0, 600)).toContain("requestWithTimeout");
  });
});
