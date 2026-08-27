/** PhaseG-H2: classify by existing JSON-RPC codes and client-local error classes.
 * Does not add schema fields or invent error.data.error_code.
 */

import {
  ProtocolDisconnectError,
  ProtocolRpcError,
  ProtocolTimeoutError,
} from "./client.ts";

export type ErrorHandling = "retry" | "user" | "unrecoverable";

export type HandshakeErrorCode =
  | "timeout"
  | "connection_closed"
  | "unsupported_feature"
  | "configuration_missing"
  | "server_overloaded"
  | "protocol_mismatch"
  | "rpc_error";

export interface ClassifiedError {
  code: HandshakeErrorCode;
  handling: ErrorHandling;
  message: string;
  rpcCode?: number;
}

/** JSON-RPC codes from appserver + B2 JSONRPC_STABLE_CODE. No schema fields added. */
const RPC_CODE_MAP: Record<number, { code: HandshakeErrorCode; handling: ErrorHandling }> = {
  [-32601]: { code: "unsupported_feature", handling: "user" },
  [-32602]: { code: "configuration_missing", handling: "user" },
  [-32002]: { code: "configuration_missing", handling: "user" },
  [-32004]: { code: "timeout", handling: "retry" },
  [-32006]: { code: "protocol_mismatch", handling: "unrecoverable" },
  [-32007]: { code: "configuration_missing", handling: "user" },
  [-32008]: { code: "server_overloaded", handling: "retry" },
  [-32009]: { code: "connection_closed", handling: "retry" },
};

function classified(
  code: HandshakeErrorCode,
  handling: ErrorHandling,
  message: string,
  rpcCode?: number,
): ClassifiedError {
  return { code, handling, message, rpcCode };
}

export function handlingFor(code: HandshakeErrorCode): ErrorHandling {
  if (code === "timeout" || code === "connection_closed" || code === "server_overloaded") return "retry";
  if (code === "unsupported_feature" || code === "configuration_missing") return "user";
  return "unrecoverable";
}

export function classifyProtocolError(error: unknown): ClassifiedError {
  if (error instanceof ProtocolTimeoutError) {
    return classified("timeout", "retry", error.message, error.code);
  }
  if (error instanceof ProtocolDisconnectError) {
    return classified("connection_closed", "retry", error.message, error.code);
  }
  if (error instanceof ProtocolRpcError) {
    const mapped = RPC_CODE_MAP[error.code];
    if (mapped) {
      return classified(mapped.code, mapped.handling, error.message, error.code);
    }
    return classified("rpc_error", "unrecoverable", error.message, error.code);
  }
  const message = error instanceof Error ? error.message : String(error);
  return classified("rpc_error", "unrecoverable", message);
}

export function disconnectError(reason: string): ClassifiedError {
  return classified("connection_closed", "retry", reason);
}
