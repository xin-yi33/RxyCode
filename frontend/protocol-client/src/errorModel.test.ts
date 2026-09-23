import { describe, expect, test } from "bun:test";
import {
  ProtocolDisconnectError,
  ProtocolRpcError,
  ProtocolTimeoutError,
} from "./client.ts";
import { classifyProtocolError } from "./errorModel.ts";

describe("PhaseG-H2 error classification", () => {
  test("timeout class is retryable", () => {
    expect(classifyProtocolError(new ProtocolTimeoutError("initialize"))).toMatchObject({
      code: "timeout",
      handling: "retry",
    });
  });

  test("-32601 is unsupported_feature / user", () => {
    expect(
      classifyProtocolError(new ProtocolRpcError({ code: -32601, message: "Method not found" })),
    ).toMatchObject({
      code: "unsupported_feature",
      handling: "user",
    });
  });

  test("-32602 is configuration_missing / user", () => {
    expect(
      classifyProtocolError(
        new ProtocolRpcError({ code: -32602, message: "workspace_root is required" }),
      ),
    ).toMatchObject({
      code: "configuration_missing",
      handling: "user",
    });
  });

  test("-32002 is configuration_missing / user", () => {
    expect(
      classifyProtocolError(new ProtocolRpcError({ code: -32002, message: "call initialize first" })),
    ).toMatchObject({
      code: "configuration_missing",
      handling: "user",
    });
  });

  test("generic -32000 is unrecoverable rpc_error", () => {
    expect(
      classifyProtocolError(new ProtocolRpcError({ code: -32000, message: "server overloaded" })),
    ).toMatchObject({
      code: "rpc_error",
      handling: "unrecoverable",
    });
  });

  test("-32008 is overloaded / retry", () => {
    expect(
      classifyProtocolError(new ProtocolRpcError({ code: -32008, message: "overloaded" })),
    ).toMatchObject({
      code: "server_overloaded",
      handling: "retry",
    });
  });

  test("disconnect class is retryable connection_closed", () => {
    expect(classifyProtocolError(new ProtocolDisconnectError("appserver exited"))).toMatchObject({
      code: "connection_closed",
      handling: "retry",
    });
  });
});
