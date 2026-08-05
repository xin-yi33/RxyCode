import { ProtocolClient, ProtocolRpcError } from "@rxycode/protocol-client";
import type { Subprocess } from "bun";
import { appendFileSync } from "node:fs";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamReduceState,
} from "../streamReducer.ts";
import type { Mode, StatusInfo } from "../types.ts";
import {
  httpFetchStatus,
  httpSendCommand,
  type CommandResult,
} from "./httpAdmin.ts";
import { notifyToStreamEvent } from "./notifyToStreamEvent.ts";
import { shouldClearStreamingOnNotify } from "./streamLifecycle.ts";
import type { ChatApiCallbacks, ChatTransport } from "./types.ts";

const DEFAULT_INIT_TIMEOUT_MS = 10_000;
const DEFAULT_SESSION_TIMEOUT_MS = 10_000;

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString().slice(2, 7)}`;
}

function initTimeoutMs(): number {
  const raw = Number(process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_INIT_TIMEOUT_MS;
}

function sessionTimeoutMs(): number {
  const raw = Number(process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_SESSION_TIMEOUT_MS;
}

type PromptResult = {
  run_id?: string;
  status?: string;
  text?: string;
  thinking?: string;
  input_tokens?: number;
  output_tokens?: number;
};

let pythonCmdOverride: string[] | null = null;
/** Survives session recreate (e.g. /model switch). */
let thinkingExpandedPref = false;

/** Test hook: override appserver spawn command. */
export function __setPythonCmdForTests(cmd: string[] | null): void {
  pythonCmdOverride = cmd;
}

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
  private approvalTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private activePromptAbort: AbortController | null = null;
  private activeCallbacks: ChatApiCallbacks | null = null;

  private projectRoot(): string {
    return process.env.RXYCODE_PROJECT_ROOT ?? process.cwd();
  }

  private pythonCmd(): string[] {
    if (pythonCmdOverride) return pythonCmdOverride;
    const exe = process.env.RXYCODE_APPSERVER_PYTHON ?? "python";
    return [exe, "-m", "appserver"];
  }

  private workspaceRoot(): string {
    return process.env.RXYCODE_WORKSPACE_ROOT ?? this.projectRoot();
  }

  private clearPendingApprovals(decision: ApprovalDecision = "rejected"): void {
    for (const timer of this.approvalTimers.values()) {
      clearTimeout(timer);
    }
    this.approvalTimers.clear();
    for (const resolve of this.pendingApprovals.values()) {
      resolve(decision);
    }
    this.pendingApprovals.clear();
  }

  private resetSession(reason?: Error): void {
    this.clearPendingApprovals();
    if (this.client) {
      this.client.rejectAllPending(
        reason ?? new Error("appserver session reset"),
      );
    }
    try {
      this.proc?.kill();
    } catch {
      // ignore
    }
    this.proc = null;
    this.client = null;
    this.sessionId = null;
    this.ready = null;
  }

  async ensureReady(): Promise<ProtocolClient> {
    if (this.ready) {
      try {
        await this.ready;
      } catch (err) {
        this.resetSession(err instanceof Error ? err : new Error(String(err)));
        throw err;
      }
      if (this.client) return this.client;
    }

    this.ready = this.start();
    try {
      await this.ready;
    } catch (err) {
      this.resetSession(err instanceof Error ? err : new Error(String(err)));
      throw err;
    }

    if (!this.client) {
      throw new Error("appserver stdio client failed to start");
    }
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
        const timer = setTimeout(() => {
          if (!this.pendingApprovals.has(requestId)) return;
          this.approvalTimers.delete(requestId);
          this.pendingApprovals.delete(requestId);
          resolve("rejected");
        }, 120_000);
        this.approvalTimers.set(requestId, timer);
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
      if (!stderr) return;
      const logPath = (process.env.RXYCODE_APPSERVER_LOG || "").trim();
      const errReader = stderr.getReader();
      const errDec = new TextDecoder();
      try {
        while (true) {
          const { done, value } = await errReader.read();
          if (done) break;
          const text = errDec.decode(value);
          if (!text.trim() || !logPath) continue;
          try {
            appendFileSync(logPath, text);
          } catch {
            // ignore log write failures
          }
        }
      } catch {
        // process exiting
      }
    })();

    void (async () => {
      const reader = stdout.getReader();
      let buffer = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            client.rejectAllPending(new Error("appserver stdout closed"));
            this.resetSession(new Error("appserver stdout closed"));
            break;
          }
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
        client.rejectAllPending(new Error("appserver stdout reader failed"));
        this.resetSession(new Error("appserver stdout reader failed"));
      }
    })();

    void (async () => {
      const proc = this.proc;
      if (!proc) return;
      const exitCode = await proc.exited;
      client.rejectAllPending(new Error(`appserver exited (${exitCode})`));
      if (this.proc === proc) {
        this.resetSession(new Error(`appserver exited (${exitCode})`));
      }
    })();

    await client.requestWithTimeout(
      "initialize",
      {
        client_name: "opentui",
        client_version: "1.2.5",
        protocol_version: "1.0.0",
      },
      initTimeoutMs(),
    );
    const session = (await client.requestWithTimeout<{ session_id: string }>(
      "session/new",
      { workspace_root: this.workspaceRoot() },
      sessionTimeoutMs(),
    )) as { session_id: string };
    this.sessionId = session.session_id;
    // Fire-and-forget warm so the first user prompt is not blocked on Agent ctor.
    void this.warmBootstrap().catch(() => {
      // best-effort; first prompt will bootstrap again
    });
  }

  async warmBootstrap(timeoutSeconds = 180): Promise<void> {
    const client = await this.ensureReady();
    if (!this.sessionId) {
      throw new Error("appserver session not ready");
    }
    await client.request("session/warm", {
      session_id: this.sessionId,
      timeout_seconds: timeoutSeconds,
    });
  }

  async setThinkingExpanded(expanded: boolean): Promise<{
    ok: boolean;
    expanded: boolean;
    action?: string;
    message?: string;
  }> {
    const client = await this.ensureReady();
    if (!this.sessionId) {
      throw new Error("appserver session not ready");
    }
    const result = (await client.request("session/set_thinking_expanded", {
      session_id: this.sessionId,
      expanded,
    })) as {
      ok?: boolean;
      expanded?: boolean;
      action?: string;
      message?: string;
    };
    thinkingExpandedPref = Boolean(result.expanded ?? expanded);
    return {
      ok: result.ok !== false,
      expanded: thinkingExpandedPref,
      action: result.action ?? "thinking_toggled",
      message:
        result.message ??
        ("思考过程: " + (thinkingExpandedPref ? "展开" : "折叠")),
    };
  }

  toggleThinkingExpanded(): Promise<{
    ok: boolean;
    expanded: boolean;
    action?: string;
    message?: string;
  }> {
    return this.setThinkingExpanded(!thinkingExpandedPref);
  }

  resolveApproval(approvalId: string, decision: ApprovalDecision): boolean {
    const resolve = this.pendingApprovals.get(approvalId);
    if (!resolve) return false;
    const timer = this.approvalTimers.get(approvalId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.approvalTimers.delete(approvalId);
    }
    this.pendingApprovals.delete(approvalId);
    resolve(decision);
    return true;
  }

  async interrupt(): Promise<void> {
    if (!this.sessionId) return;
    try {
      const client = await this.ensureReady();
      await client.request("session/interrupt", { session_id: this.sessionId });
    } catch {
      // best-effort
    }
    this.activePromptAbort?.abort();
  }

  async sendChatMessage(
    content: string,
    mode: Mode,
    callbacks: ChatApiCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
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

    try {
      const client = await this.ensureReady();
      if (!this.sessionId) {
        throw new Error("appserver session not ready");
      }
      callbacks.onProgress?.("");

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
      let sawStreamActivity = false;
      let streamingCleared = false;
      const clearStreamingEarly = () => {
        if (streamingCleared) return;
        streamingCleared = true;
        callbacks.onStreaming(false);
        callbacks.onProgress?.("");
      };
      client.onNotification = (method, params) => {
        priorOnNotification?.(method, params);
        const event = notifyToStreamEvent(method, params);
        if (!event) return;
        if (!sawStreamActivity) {
          sawStreamActivity = true;
          callbacks.onProgress?.("");
        }
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
        if (shouldClearStreamingOnNotify(method)) {
          publish({
            ...state,
            messages: settleActiveMessages(state.messages),
          });
          clearStreamingEarly();
        }
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
          thinking_expanded: thinkingExpandedPref,
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
          publish({
            ...state,
            messages: [
              ...settleActiveMessages(state.messages),
              {
                id: newId("system"),
                role: "system",
                content: e.message,
                timestamp: Date.now(),
              },
            ],
          });
        } else {
          publish({
            ...state,
            messages: [
              ...settleActiveMessages(state.messages),
              {
                id: newId("system"),
                role: "system",
                content: e instanceof Error ? e.message : String(e),
                timestamp: Date.now(),
              },
            ],
          });
        }
      } finally {
        client.onNotification = priorOnNotification;
        this.activeCallbacks = null;
        this.activePromptAbort = null;
        signal?.removeEventListener("abort", onAbort);
      }
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "appserver 启动失败，请检查 Python 路径";
      callbacks.onMessages((prev) => [
        ...prev,
        {
          id: newId("system"),
          role: "system",
          content: `启动失败: ${message}`,
          timestamp: Date.now(),
        },
      ]);
      callbacks.onStatus(null);
    } finally {
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
    this.resetSession();
  }
}

let sharedSession = new StdioAppserverSession();

export const stdioTransport: ChatTransport = {
  kind: "stdio",

  async fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
    return httpFetchStatus(onStatus);
  },

  async sendCommand(command: string): Promise<CommandResult> {
    const trimmed = command.trim();
    if (trimmed === "/thinking") {
      try {
        const result = await sharedSession.toggleThinkingExpanded();
        return {
          ok: true,
          action: result.action ?? "thinking_toggled",
          message: result.message,
          expanded: result.expanded,
        };
      } catch (e) {
        return {
          ok: false,
          message: e instanceof Error ? e.message : String(e),
        };
      }
    }
    const result = await httpSendCommand(command);
    if (
      result.ok &&
      trimmed.startsWith("/model ") &&
      result.action === "model_changed"
    ) {
      await sharedSession.shutdown();
      sharedSession = new StdioAppserverSession();
    }
    return result;
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

/** Best-effort pre-warm of appserver Agent bootstrap (stdio only). */
export async function warmStdioBootstrap(): Promise<void> {
  await sharedSession.warmBootstrap();
}

/** Test hook: reset shared stdio session between tests. */
export function __resetStdioSessionForTests(): void {
  void sharedSession.shutdown();
  sharedSession = new StdioAppserverSession();
  pythonCmdOverride = null;
  thinkingExpandedPref = false;
}
