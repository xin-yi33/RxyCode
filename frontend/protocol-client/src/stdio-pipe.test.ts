import { describe, expect, test } from "bun:test";
import { ProtocolClient } from "./client.ts";

/** Bidirectional newline-delimited stdio mock (client stdout -> server stdin). */
function createStdioPipe() {
  const client = new ProtocolClient((line) => {
    void server.handleLine(line);
  });
  const server = new ProtocolClient((line) => {
    void client.handleLine(line);
  });
  return { client, server };
}

describe("stdio pipe", () => {
  test("client request crosses pipe and receives server response", async () => {
    const { client, server } = createStdioPipe();
    server.onServerRequest = async (method, params) => {
      expect(method).toBe("initialize");
      expect(params).toMatchObject({
        client_name: "opentui",
        protocol_version: "1.0.0",
      });
      return { protocol_version: "1.0.0", server_name: "appserver" };
    };

    const result = await client.request("initialize", {
      client_name: "opentui",
      client_version: "0.1.0",
      protocol_version: "1.0.0",
    });

    expect(result).toEqual({
      protocol_version: "1.0.0",
      server_name: "appserver",
    });
  });

  test("server notification crosses pipe to client handler", async () => {
    const { client, server } = createStdioPipe();
    const seen: string[] = [];
    client.onNotification = (method) => {
      seen.push(method);
    };

    server.notify("event/message_delta", {
      session_id: "s1",
      text: "hello",
    });

    expect(seen).toEqual(["event/message_delta"]);
  });

  test("approval request round-trips over stdio pipe", async () => {
    const { client, server } = createStdioPipe();
    client.onServerRequest = async (_method, params) => ({
      request_id: (params as { request_id: string }).request_id,
      decision: "approved",
    });

    const replyPromise = server.request("approval/request", {
      session_id: "s1",
      request_id: "apr-1",
      risk_level: "WRITE",
      action: "write_file",
      details: {},
    });

    await expect(replyPromise).resolves.toEqual({
      request_id: "apr-1",
      decision: "approved",
    });
  });
});