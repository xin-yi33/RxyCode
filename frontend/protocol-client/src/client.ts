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

  onServerRequest?: ServerRequestHandler;
  onNotification?: NotificationHandler;

  constructor(writeLine: (line: string) => void) {
    this.writeLine = writeLine;
  }

  private send(message: Record<string, unknown>): void {
    this.writeLine(JSON.stringify(message));
  }

  notify(method: string, params?: unknown): void {
    const message: Record<string, unknown> = { jsonrpc: "2.0", method };
    if (params !== undefined) {
      message.params = params;
    }
    this.send(message);
  }

  request<T = unknown>(method: string, params?: unknown): Promise<T> {
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