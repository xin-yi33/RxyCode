import { describe, expect, test } from "bun:test";
import { ProtocolClient, ProtocolRpcError } from "./client.ts";

function createHarness() {
  const outbound: string[] = [];
  const client = new ProtocolClient((line) => outbound.push(line));
  return { client, outbound };
}

describe("ProtocolClient", () => {
  test("request/response pairing by id", async () => {
    const { client, outbound } = createHarness();
    const responsePromise = client.request("initialize", {
      client_name: "test",
      client_version: "0.0.0",
      protocol_version: "1.0.0",
    });

    expect(outbound).toHaveLength(1);
    const sent = JSON.parse(outbound[0]!);
    expect(sent.jsonrpc).toBe("2.0");
    expect(sent.method).toBe("initialize");
    expect(sent.id).toBe(1);

    await client.handleLine(
      JSON.stringify({ jsonrpc: "2.0", id: 1, result: { ok: true } }),
    );

    await expect(responsePromise).resolves.toEqual({ ok: true });
  });

  test("notifications without id", async () => {
    const { client } = createHarness();
    const seen: Array<{ method: string; params: unknown }> = [];
    client.onNotification = (method, params) => {
      seen.push({ method, params });
    };

    client.notify("session/event", { type: "token", text: "hi" });
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        method: "session/progress",
        params: { step: 1 },
      }),
    );

    expect(seen).toEqual([
      { method: "session/progress", params: { step: 1 } },
    ]);
  });

  test("bidirectional approval server request", async () => {
    const { client, outbound } = createHarness();
    client.onServerRequest = async (method, params) => {
      expect(method).toBe("approval/request");
      expect(params).toEqual({
        session_id: "s1",
        request_id: "r1",
        risk_level: "WRITE",
        action: "write_file",
        details: {},
      });
      return { request_id: "r1", decision: "approved" };
    };

    const handlePromise = client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 42,
        method: "approval/request",
        params: {
          session_id: "s1",
          request_id: "r1",
          risk_level: "WRITE",
          action: "write_file",
          details: {},
        },
      }),
    );

    await handlePromise;
    expect(outbound).toHaveLength(1);
    const reply = JSON.parse(outbound[0]!);
    expect(reply).toEqual({
      jsonrpc: "2.0",
      id: 42,
      result: { request_id: "r1", decision: "approved" },
    });
  });

  test("error response rejects pending request", async () => {
    const { client } = createHarness();
    const responsePromise = client.request("session/new", {
      workspace_root: "/tmp",
    });

    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        error: { code: -32000, message: "workspace missing" },
      }),
    );

    await expect(responsePromise).rejects.toBeInstanceOf(ProtocolRpcError);
    await expect(responsePromise).rejects.toMatchObject({
      code: -32000,
      message: "workspace missing",
    });
  });
});