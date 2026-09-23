/** PhaseG-H2 handshake: initialize/initialized, version range, capabilities.
 * Consumes appserver initialize result. Does not author schema.
 */

import { ProtocolClient, type JsonRpcId } from "./client.ts";
import {
  classifyProtocolError,
  disconnectError,
  type ClassifiedError,
} from "./errorModel.ts";
import type { InitializeRequest } from "./generated/types.ts";

export const DEFAULT_PROTOCOL_VERSION = "1.1.0";
export const PROTOCOL_VERSION_MIN = "1.0.0";
export const PROTOCOL_VERSION_MAX = "1.1.0";
const SEMVER =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$/;

export function isValidProtocolVersion(version: unknown): version is string {
  return typeof version === "string" && SEMVER.test(version);
}

export type HandshakeStatus = "pending" | "started" | "completed" | "failed";

export type InitializeResult = {
  protocol_version: string;
  server_name?: string;
  capabilities?: Record<string, unknown> | null;
};

export type HandshakeState =
  | { status: "pending" }
  | { status: "started" }
  | {
      status: "completed";
      protocolVersion: string;
      serverName: string;
      capabilities: Record<string, unknown>;
    }
  | { status: "failed"; error: ClassifiedError };

export type ProtocolMatch =
  | { ok: true; protocolVersion: string }
  | {
      ok: false;
      code: "protocol_mismatch";
      clientVersion: string;
      serverVersion: string;
    };

export function isVersionInRange(
  version: unknown,
  minInclusive: unknown,
  maxInclusive: unknown,
): boolean {
  if (!isValidProtocolVersion(version) || !isValidProtocolVersion(minInclusive) || !isValidProtocolVersion(maxInclusive)) {
    return false;
  }
  return compareSemver(version, minInclusive) >= 0 && compareSemver(version, maxInclusive) <= 0;
}

function versionCore(version: string): number[] {
  const core = version.split("+")[0]!.split("-")[0]!;
  return core.split(".").map((part) => Number.parseInt(part, 10) || 0);
}

function prereleaseIds(version: string): string[] | null {
  const noBuild = version.split("+")[0]!;
  const dash = noBuild.indexOf("-");
  if (dash < 0) return null;
  return noBuild.slice(dash + 1).split(".");
}

function comparePrereleaseId(a: string, b: string): number {
  const aNum = /^\d+$/.test(a);
  const bNum = /^\d+$/.test(b);
  if (aNum && bNum) {
    const da = Number(a);
    const db = Number(b);
    if (da < db) return -1;
    if (da > db) return 1;
    return 0;
  }
  if (aNum && !bNum) return -1;
  if (!aNum && bNum) return 1;
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function compareSemver(a: string, b: string): number {
  const pa = versionCore(a);
  const pb = versionCore(b);
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i += 1) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da > db) return 1;
    if (da < db) return -1;
  }
  const ra = prereleaseIds(a);
  const rb = prereleaseIds(b);
  if (ra === null && rb === null) return 0;
  if (ra !== null && rb === null) return -1;
  if (ra === null && rb !== null) return 1;
  const idsA = ra ?? [];
  const idsB = rb ?? [];
  const count = Math.max(idsA.length, idsB.length);
  for (let i = 0; i < count; i += 1) {
    if (i >= idsA.length) return -1;
    if (i >= idsB.length) return 1;
    const cmp = comparePrereleaseId(idsA[i]!, idsB[i]!);
    if (cmp !== 0) return cmp;
  }
  return 0;
}

export function matchProtocolVersion(
  clientExpected: unknown,
  serverReported: unknown,
): ProtocolMatch {
  const clientVersion = typeof clientExpected === "string" ? clientExpected : "";
  const serverVersion = typeof serverReported === "string" ? serverReported : "";
  if (!isValidProtocolVersion(clientVersion) || !isValidProtocolVersion(serverVersion)) {
    return {
      ok: false,
      code: "protocol_mismatch",
      clientVersion,
      serverVersion,
    };
  }
  if (!isVersionInRange(serverVersion, clientVersion, clientVersion)) {
    return {
      ok: false,
      code: "protocol_mismatch",
      clientVersion,
      serverVersion,
    };
  }
  return { ok: true, protocolVersion: serverVersion };
}

export function isDeclaredCapability(
  serverCapabilities: Readonly<Record<string, unknown>> | null | undefined,
  name: string,
): boolean {
  if (serverCapabilities == null || name.length === 0) {
    return false;
  }
  return serverCapabilities[name] === true;
}

export type ProtocolVersionRange = {
  min: string;
  max: string;
};

export type InitializeHandshakeOptions = {
  timeoutMs?: number;
  versionRange?: ProtocolVersionRange;
};

export async function initializeHandshake(
  client: ProtocolClient,
  params: InitializeRequest,
  options: InitializeHandshakeOptions = {},
): Promise<HandshakeState> {
  const range = options.versionRange ?? {
    min: PROTOCOL_VERSION_MIN,
    max: PROTOCOL_VERSION_MAX,
  };
  try {
    const result = await client.requestWithTimeout<InitializeResult | null>(
      "initialize",
      params,
      options.timeoutMs ?? 10_000,
    );
    if (result === null || typeof result !== "object" || Array.isArray(result)) {
      return {
        status: "failed",
        error: {
          code: "protocol_mismatch",
          handling: "unrecoverable",
          message: "protocol mismatch: initialize result is not an object",
        },
      };
    }
    const rawVersion = (result as InitializeResult).protocol_version;
    const serverVersion = typeof rawVersion === "string" ? rawVersion : "";
    if (!isVersionInRange(serverVersion, range.min, range.max)) {
      return {
        status: "failed",
        error: {
          code: "protocol_mismatch",
          handling: "unrecoverable",
          message: `protocol mismatch: supported ${range.min}..${range.max} server ${serverVersion}`,
        },
      };
    }
    client.notify("initialized");
    const capabilities =
      result.capabilities && typeof result.capabilities === "object"
        ? result.capabilities
        : {};
    return {
      status: "completed",
      protocolVersion: serverVersion,
      serverName: typeof result.server_name === "string" ? result.server_name : "",
      capabilities,
    };
  } catch (error) {
    return { status: "failed", error: classifyProtocolError(error) };
  }
}

export function applyDisconnect(reason: string): HandshakeState {
  return { status: "failed", error: disconnectError(reason) };
}

/** §3.1 consumer transport. JSON-RPC ids stay on ProtocolClient. */
export type ProtocolEvent = { method: string; params: unknown };

export type ClientTransport = {
  initialize(params: InitializeRequest): Promise<HandshakeState>;
  request<T>(method: string, params?: unknown): Promise<T>;
  subscribe(listener: (event: ProtocolEvent) => void): () => void;
  cancel(requestId: JsonRpcId): Promise<void>;
  close(reason: string): Promise<void>;
};

export function createClientTransport(client: ProtocolClient): ClientTransport {
  const listeners = new Set<(event: ProtocolEvent) => void>();
  const previous = client.onNotification;
  client.onNotification = (method, params) => {
    previous?.(method, params);
    const event = { method, params };
    for (const listener of listeners) listener(event);
  };
  return {
    initialize: (params) => initializeHandshake(client, params),
    request: (method, params) => client.request(method, params),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    cancel: async (requestId) => {
      await Promise.resolve(client.cancel(requestId));
    },
    close: async (reason) => {
      await Promise.resolve(client.close(reason));
    },
  };
}
