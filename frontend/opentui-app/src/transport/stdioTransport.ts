import { ProtocolClient, ProtocolRpcError } from "@rxycode/protocol-client";
import type { Subprocess } from "bun";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamReduceState,
} from "../streamReducer.ts";
import type { Mode, StatusInfo } from "../types.ts";
import { notifyToStreamEvent } from "./notifyToStreamEvent.ts";
import type { ChatApiCallbacks, ChatTransport } from "./types.ts";

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 7)}`;
}

type PromptResult = {
  run_id?: string;
  status?: string;
  text?: string;
  thinking?: string;
  input_tokens?: number;
  output_tokens?: number;
};

class StdioAppserverSession {
  private proc: Subprocess<"pipe", "pipe", "pipe"> | null = null;
  private client: ProtocolClient | null = null;
  private sessionId: string | null = null;
  private ready: Promise<void> | null = null;
  private lastStatus: StatusInfo | null = null;
  private pendingApprovals = new Map<
    string,
    (decision: ApprovalDecision) => void
  >();
  private activePromptAbort: AbortController | null = null;
  private activeCallbacks: ChatApiCallbacks | null = null;

  private projectRoot(): string {
    return process.env.RXYCODE_PROJECT_ROOT ?? process.cwd();
  }

  private pythonCmd(): string[] {
    const exe = process.env.RXYCODE_APPSERVER_PYTHON ?? "python";
    return [exe, "-m", "appserver"];
  }

  private workspaceRoot(): string {
    return process.env.RXYCODE_WORKSPACE_ROOT ?? this.projectRoot();
  }

  async ensureReady(): Promise<ProtocolClient> {
    if (this.ready) {
      await this.ready;
      if (this.client) return this.client;
    }
    this.ready = this.start();
    await this.ready;
    if (!this.client) throw new Error("appserver stdio client failed to start");
    return this.client;
  }

  private async start(): Promise<void> {
    const env: Record<string, string> = {
      ...Object.fromEntries(
        Object.entries(process.env).filter((e): e is [string, string] => e[1] !== undefined),
      ),
      PYTHONIOENCODING: "utf-8",
      PYTHONPATH: this.projectRoot(),
    };
    if (process.env.RXYCODE_APPSERVER_STUB === "1") {
      env.RXYCODE_APPSERVER_STUB = "1";
    }

    this.proc = Bun.spawn(this.pythonCmd(), {
      cwd: this.projectRoot(),
      env,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
    });

    const stdin = this.proc.stdin;
    const stdout = this.proc.stdout;
    if (!stdin || !stdout) {
      throw new Error("appserver subprocess missing stdio pipes");
    }

    const encoder = new TextEncoder();
    const decoder = new TextDecoder();
    const client = new ProtocolClient((line) => {
      stdin.write(encoder.encode(`${line}\n`));
    });
    this.client = client;

    client.onServerRequest = async (method, params) => {
      if (method !== "approval/request") {
        return { decision: "rejected" };
      }
      const payload = (params ?? {}) as Record<string, unknown>;
      const requestId = String(payload.request_id ?? "");
      const details = payload.details as Record<string, unknown> | undefined;
      const argsRaw = details?.args;
      const decision = await new Promise<ApprovalDecision>((resolve) => {
        this.pendingApprovals.set(requestId, resolve);
        setTimeout(() => {
          if (this.pendingApprovals.has(requestId)) {
            this.pendingApprovals.delete(requestId);
            resolve("rejected");
          }
        }, 120_000);
        this.activeCallbacks?.onApprovalRequest?.({
          approvalId: requestId,
          tool: String(payload.action ?? "unknown"),
          risk: String(payload.risk_level ?? "WRITE"),
          args:
            typeof argsRaw === "string"
              ? argsRaw
              : JSON.stringify(argsRaw ?? details ?? {}),
        });
      });
      this.activeCallbacks?.onApprovalRequest?.(null);
      return { request_id: requestId, decision };
    };

    void (async () => {
      const stderr = this.proc?.stderr;
      if (stderr) {
        const errReader = stderr.getReader();
        const errDec = new TextDecoder();
        try {
          while (true) {
            const { done, value } = await errReader.read();
            if (done) break;
            const text = errDec.decode(value);
            if (text.trim()) process.stderr.write(text);
          }
        } catch {
          // process exiting
        }
      }
    })();

    void (async () => {
      const reader = stdout.getReader();
      let buffer = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let newline = buffer.indexOf("\n");
          while (newline >= 0) {
            const line = buffer.slice(0, newline);
            buffer = buffer.slice(newline + 1);
            await client.handleLine(line);
            newline = buffer.indexOf("\n");
          }
        }
        if (buffer.trim()) {
          await client.handleLine(buffer);
        }
      } catch {
        // subprocess closed
      }
    })();

    await client.request("initialize", {
      client_name: "opentui",
      client_version: "1.2.4",
      protocol_version: "1.0.0",
    });
    const session = (await client.request<{ session_id: string }>("session/new", {
      workspace_root: this.workspaceRoot(),
    })) as { session_id: string };
    this.sessionId = session.session_id;
  }

  resolveApproval(approvalId: string, decision: ApprovalDecision): boolean {
    const resolve = this.pendingApprovals.get(approvalId);
    if (!resolve) return false;
    this.pendingApprovals.delete(approvalId);
    resolve(decision);
    return true;
  }

  async interrupt(): Promise<void> {
    if (!this.sessionId) return;
    const client = await this.ensureReady();
    try {
      await client.request("session/interrupt", { session_id: this.sessionId });
    } catch {
      // best-effort
    }
    this.activePromptAbort?.abort();
  }

  async sendCommand(command: string): Promise<Record<string, unknown> | null> {
    const client = await this.ensureReady();
    if (!this.sessionId) return null;
    try {
      const result = (await client.request<PromptResult>("session/prompt", {
        session_id: this.sessionId,
        text: command,
        timeout_seconds: 120,
      })) as PromptResult;
      return { text: result.text ?? "", status: result.status ?? "succeeded" };
    } catch {
      return null;
    }
  }

  async sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
    const client = await this.ensureReady();
    if (!this.sessionId) throw new Error("appserver session not ready");

    const userMsg = {
      id: newId("user"),
      role: "user" as const,
      content,
      timestamp: Date.now(),
      mode,
    };
    callbacks.onMessages((prev) => [...prev, userMsg]);
    callbacks.onStreaming(true);
    callbacks.onProgress?.("Connecting...");

    const thinkingId = newId("thinking");
    const assistantId = newId("assistant");

    let state: StreamReduceState = {
      messages: [
        {
          id: thinkingId,
          role: "thinking",
          content: "…",
          timestamp: Date.now(),
          live: true,
          done: false,
        },
      ],
      thinkingId,
      assistantId,
      acc: "",
      assistantCreated: false,
      reasoningAcc: "",
      hasReasoning: false,
    };

    callbacks.onMessages((prev) => [...prev, ...state.messages]);

    const publish = (next: StreamReduceState) => {
      state = next;
      callbacks.onMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === userMsg.id);
        if (idx < 0) return [...prev, ...next.messages];
        return [...prev.slice(0, idx + 1), ...next.messages];
      });
    };

    const priorOnNotification = client.onNotification;
    client.onNotification = (method, params) => {
      priorOnNotification?.(method, params);
      const event = notifyToStreamEvent(method, params);
      if (!event) return;
      if (event.type === "progress" && !state.hasReasoning) {
        callbacks.onProgress?.(event.message || event.text || "Working...");
      }
      if (event.type === "tool_call") {
        callbacks.onProgress?.(
          event.name ? `Tool: ${event.name}` : "Running tool...",
        );
      }
      if (event.type === "tool_result") {
        callbacks.onApprovalRequest?.(null);
      }
      const next = applyStreamEvent(state, event, newId);
      if (next !== state) publish(next);
    };

    this.activeCallbacks = callbacks;
    const abort = new AbortController();
    this.activePromptAbort = abort;
    const onAbort = () => void this.interrupt();
    signal?.addEventListener("abort", onAbort);
    abort.signal.addEventListener("abort", onAbort);

    try {
      const result = (await client.request<PromptResult>("session/prompt", {
        session_id: this.sessionId,
        text: content,
        mode,
        timeout_seconds: 600,
      })) as PromptResult;

      if (result.text) {
        const finalEvent = applyStreamEvent(
          state,
          { type: "final", text: result.text },
          newId,
        );
        publish(finalEvent);
      }

      publish({
        ...state,
        messages: settleActiveMessages(state.messages),
      });

      this.lastStatus = {
        input_tokens: result.input_tokens,
        output_tokens: result.output_tokens,
        mode,
      };
    } catch (e) {
      if (abort.signal.aborted || (e as Error)?.name === "AbortError") {
        publish({
          ...state,
          messages: [
            ...settleActiveMessages(state.messages, "cancelled"),
            {
              id: newId("system"),
              role: "system",
              content: "Cancelled.",
              timestamp: Date.now(),
            },
          ],
        });
      } else if (e instanceof ProtocolRpcError) {
        callbacks.onMessages((prev) => [
          ...settleActiveMessages(prev),
          {
            id: newId("system"),
            role: "system",
            content: (e as ProtocolRpcError).message,
            timestamp: Date.now(),
          },
        ]);
      } else {
        callbacks.onMessages((prev) => [
          ...settleActiveMessages(prev),
          {
            id: newId("system"),
            role: "system",
            content: e instanceof Error ? e.message : String(e),
            timestamp: Date.now(),
          },
        ]);
      }
    } finally {
      client.onNotification = priorOnNotification;
      this.activeCallbacks = null;
      this.activePromptAbort = null;
      signal?.removeEventListener("abort", onAbort);
      callbacks.onStreaming(false);
      callbacks.onProgress?.("");
      callbacks.onStatus(this.lastStatus);
    }
  }

  async shutdown(): Promise<void> {
    if (!this.client) return;
    try {
      await this.client.request("shutdown", { reason: "opentui exit" });
    } catch {
      // ignore
    }
    this.proc?.kill();
    this.proc = null;
    this.client = null;
    this.sessionId = null;
    this.ready = null;
  }
}

const sharedSession = new StdioAppserverSession();

export const stdioTransport: ChatTransport = {
  kind: "stdio",

  async fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
    onStatus(null);
  },

  async sendCommand(command: string): Promise<Record<string, unknown> | null> {
    return sharedSession.sendCommand(command);
  },

  async cancelActiveRequest(): Promise<void> {
    await sharedSession.interrupt();
  },

  async respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean> {
    return sharedSession.resolveApproval(approvalId, decision);
  },

  async sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
    await sharedSession.sendChatMessage(content, mode, callbacks, signal);
  },

  async shutdown(): Promise<void> {
    await sharedSession.shutdown();
  },
};

/** Test hook: replace shared stdio session (mock subprocess). */
export function __resetStdioSessionForTests(): void {
  // no-op placeholder; tests use notify mapper directly
}
