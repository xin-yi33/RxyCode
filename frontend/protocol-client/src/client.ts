/** JSON-RPC 2.0 newline-delimited protocol client (stdio transport). */

export type JsonRpcId = string | number;

export interface JsonRpcErrorObject {
  code: number;
  message: string;
  data?: unknown;
}

export class ProtocolRpcError extends Error {
  readonly code: number;
  readonly data?: unknown;

  constructor(error: JsonRpcErrorObject) {
    super(error.message);
    this.name = "ProtocolRpcError";
    this.code = error.code;
    this.data = error.data;
  }
}

/** Client-local timeout. Not a schema field; uses JSON-RPC implementation range. */
export class ProtocolTimeoutError extends ProtocolRpcError {
  constructor(method: string) {
    super({ code: -32000, message: `RPC timeout: ${method}` });
    this.name = "ProtocolTimeoutError";
  }
}

/** Client-local closed transport. Not a schema field. */
export class ProtocolDisconnectError extends ProtocolRpcError {
  constructor(reason = "connection closed") {
    super({ code: -32000, message: reason });
    this.name = "ProtocolDisconnectError";
  }
}

export type ServerRequestHandler = (
  method: string,
  params: unknown,
) => Promise<unknown> | unknown;

export type NotificationHandler = (
  method: string,
  params: unknown,
) => void;

type PendingEntry = {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
};

export class ProtocolClient {
  private nextId = 1;
  private readonly pending = new Map<JsonRpcId, PendingEntry>();
  private readonly writeLine: (line: string) => void;
  private closed = false;
  private closeReason = "connection closed";

  onServerRequest?: ServerRequestHandler;
  onNotification?: NotificationHandler;

  get isClosed(): boolean {
    return this.closed;
  }

  /** Read-only diagnostics; never exposes prompts, params, ids, or secrets. */
  get pendingRequestCount(): number {
    return this.pending.size;
  }

  constructor(writeLine: (line: string) => void) {
    this.writeLine = writeLine;
  }

  private send(message: Record<string, unknown>): void {
    this.writeLine(JSON.stringify(message));
  }

  private assertOpen(): void {
    if (this.closed) {
      throw new ProtocolDisconnectError(this.closeReason);
    }
  }

  notify(method: string, params?: unknown): void {
    this.assertOpen();
    const message: Record<string, unknown> = { jsonrpc: "2.0", method };
    if (params !== undefined) {
      message.params = params;
    }
    this.send(message);
  }

  request<T = unknown>(method: string, params?: unknown): Promise<T> {
    if (this.closed) {
      return Promise.reject(new ProtocolDisconnectError(this.closeReason));
    }
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
      });
      const message: Record<string, unknown> = {
        jsonrpc: "2.0",
        method,
        id,
      };
      if (params !== undefined) {
        message.params = params;
      }
      this.send(message);
    });
  }

  requestWithTimeout<T = unknown>(
    method: string,
    params?: unknown,
    timeoutMs = 10_000,
  ): Promise<T> {
    if (this.closed) {
      return Promise.reject(new ProtocolDisconnectError(this.closeReason));
    }
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        if (!this.pending.has(id)) return;
        this.pending.delete(id);
        reject(new ProtocolTimeoutError(method));
      }, timeoutMs);

      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value as T);
        },
        reject: (reason) => {
          clearTimeout(timer);
          reject(reason);
        },
      });

      const message: Record<string, unknown> = {
        jsonrpc: "2.0",
        method,
        id,
      };
      if (params !== undefined) {
        message.params = params;
      }
      this.send(message);
    });
  }

  rejectAllPending(reason: Error): void {
    for (const [, entry] of this.pending) {
      entry.reject(reason);
    }
    this.pending.clear();
  }

  cancel(id: JsonRpcId, reason = "RPC cancelled"): void {
    const entry = this.pending.get(id);
    if (!entry) return;
    this.pending.delete(id);
    entry.reject(new ProtocolTimeoutError(reason));
  }

  close(reason = "connection closed"): void {
    this.closed = true;
    this.closeReason = reason;
    this.rejectAllPending(new ProtocolDisconnectError(reason));
  }

  respond(id: JsonRpcId, result: unknown): void {
    this.send({ jsonrpc: "2.0", id, result });
  }

  respondError(
    id: JsonRpcId,
    code: number,
    message: string,
    data?: unknown,
  ): void {
    const error: JsonRpcErrorObject = { code, message };
    if (data !== undefined) {
      error.data = data;
    }
    this.send({ jsonrpc: "2.0", id, error });
  }

  async handleLine(line: string): Promise<void> {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    let message: Record<string, unknown>;
    try {
      message = JSON.parse(trimmed) as Record<string, unknown>;
    } catch {
      return;
    }

    const method = message.method;
    const hasMethod = typeof method === "string";
    const hasId = Object.prototype.hasOwnProperty.call(message, "id");
    const id = message.id as JsonRpcId | undefined;

    if (hasMethod && !hasId) {
      this.onNotification?.(method, message.params);
      return;
    }

    const isResponse =
      hasId &&
      (Object.prototype.hasOwnProperty.call(message, "result") ||
        Object.prototype.hasOwnProperty.call(message, "error"));

    if (isResponse && id !== undefined) {
      const entry = this.pending.get(id);
      if (!entry) {
        return;
      }
      this.pending.delete(id);
      if (Object.prototype.hasOwnProperty.call(message, "error")) {
        const error = message.error as JsonRpcErrorObject;
        entry.reject(new ProtocolRpcError(error));
      } else {
        entry.resolve(message.result);
      }
      return;
    }

    if (hasMethod && hasId && id !== undefined) {
      if (!this.onServerRequest) {
        this.respondError(id, -32601, "Method not found");
        return;
      }
      try {
        const result = await this.onServerRequest(method, message.params);
        this.respond(id, result ?? null);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        this.respondError(id, -32603, msg);
      }
    }
  }
}
