import { describe, expect, test } from "bun:test";
import { ProtocolClient } from "./client.ts";
import {
  createClientTransport,
  initializeHandshake,
  isDeclaredCapability,
  isValidProtocolVersion,
  isVersionInRange,
  matchProtocolVersion,
} from "./handshake.ts";

function createHarness() {
  const outbound: string[] = [];
  const client = new ProtocolClient((line) => outbound.push(line));
  return { client, outbound };
}

describe("PhaseG-H2 handshake", () => {
  test("completed initialize records server capabilities", async () => {
    const { client, outbound } = createHarness();
    const pending = initializeHandshake(client, {
      method: "initialize",
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
      capabilities: { desktop: true },
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        result: {
          protocol_version: "1.1.0",
          server_name: "rxycode-appserver",
          capabilities: { sessions: true, approval: true, models: true },
        },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("completed");
    if (state.status === "completed") {
      expect(state.protocolVersion).toBe("1.1.0");
      expect(isDeclaredCapability(state.capabilities, "sessions")).toBe(true);
      expect(isDeclaredCapability(state.capabilities, "auto_review")).toBe(false);
      expect(isDeclaredCapability(state.capabilities, "multi_agent")).toBe(false);
    }
    const initialized = outbound.map((line) => JSON.parse(line) as { method?: string }).find((message) => message.method === "initialized");
    expect(initialized).toBeDefined();
  });

  test("undeclared capability is never enabled", () => {
    expect(isDeclaredCapability({ threads: true }, "threads")).toBe(true);
    expect(isDeclaredCapability({ threads: true }, "auto_review")).toBe(false);
    expect(isDeclaredCapability({ auto_review: false }, "auto_review")).toBe(false);
    expect(isDeclaredCapability({}, "models")).toBe(false);
  });

  test("protocol mismatch is a failed unrecoverable handshake", async () => {
    const { client, outbound } = createHarness();
    const pending = initializeHandshake(client, {
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        result: { protocol_version: "2.0.0", server_name: "rxycode-appserver", capabilities: {} },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("failed");
    if (state.status === "failed") {
      expect(state.error.code).toBe("protocol_mismatch");
      expect(state.error.handling).toBe("unrecoverable");
    }
  });

  test("timeout is a retryable failed handshake", async () => {
    const { client } = createHarness();
    const state = await initializeHandshake(
      client,
      {
        client_name: "rxycode-desktop",
        client_version: "1.3.0",
        protocol_version: "1.1.0",
      },
      { timeoutMs: 20 },
    );
    expect(state.status).toBe("failed");
    if (state.status === "failed") {
      expect(state.error.code).toBe("timeout");
      expect(state.error.handling).toBe("retry");
    }
  });

  test("unsupported feature is user handling", async () => {
    const { client, outbound } = createHarness();
    const pending = initializeHandshake(client, {
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        error: { code: -32601, message: "Method not found" },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("failed");
    if (state.status === "failed") {
      expect(state.error.code).toBe("unsupported_feature");
      expect(state.error.handling).toBe("user");
    }
  });

  test("generic -32000 is unrecoverable and does not send initialized", async () => {
    const { client, outbound } = createHarness();
    const pending = initializeHandshake(client, {
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        error: { code: -32000, message: "server overloaded" },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("failed");
    if (state.status === "failed") {
      expect(state.error.code).toBe("rpc_error");
      expect(state.error.handling).toBe("unrecoverable");
    }
    expect(outbound.some((line) => JSON.parse(line).method === "initialized")).toBe(false);
  });

  test("configuration missing is user handling", async () => {
    const { client, outbound } = createHarness();
    const pending = initializeHandshake(client, {
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        error: { code: -32602, message: "workspace_root is required" },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("failed");
    if (state.status === "failed") {
      expect(state.error.code).toBe("configuration_missing");
      expect(state.error.handling).toBe("user");
    }
  });

  test("version range accepts 1.0.0..1.1.0 and rejects invalid semver", () => {
    expect(isVersionInRange("1.1.0", "1.0.0", "1.1.0")).toBe(true);
    expect(isVersionInRange("1.0.0", "1.0.0", "1.1.0")).toBe(true);
    expect(isVersionInRange("1.1.0-beta.1", "1.0.0", "1.1.0")).toBe(true);
    expect(isVersionInRange("1.1.0-beta.10", "1.1.0-beta.2", "1.1.0")).toBe(true);
    expect(isVersionInRange("1.1.0-beta.2", "1.1.0-beta.10", "1.1.0")).toBe(false);
    expect(isVersionInRange("2.0.0", "1.0.0", "1.1.0")).toBe(false);
    expect(isVersionInRange("01.2.3", "1.0.0", "1.1.0")).toBe(false);
    expect(matchProtocolVersion("1.1.0", "1.1.0").ok).toBe(true);
    expect(matchProtocolVersion(null, 1.1).ok).toBe(false);
    expect(isValidProtocolVersion({ toString: () => "1.1.0" })).toBe(false);
  });

  test("ClientTransport initialize and close", async () => {
    const { client, outbound } = createHarness();
    const transport = createClientTransport(client);
    const pending = transport.initialize({
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: "1.1.0",
    });
    const sent = JSON.parse(outbound[0]!);
    await client.handleLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: sent.id,
        result: { protocol_version: "1.1.0", server_name: "appserver", capabilities: { sessions: true } },
      }),
    );
    const state = await pending;
    expect(state.status).toBe("completed");
    const hung = client.request("session/new", { workspace_root: "D:/repo" });
    await transport.close("appserver exited");
    await expect(hung).rejects.toThrow("appserver exited");
    await expect(transport.request("session/new", { workspace_root: "D:/repo" })).rejects.toThrow(
      "appserver exited",
    );
    expect(client.isClosed).toBe(true);
  });
});
