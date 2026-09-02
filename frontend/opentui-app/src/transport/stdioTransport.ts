import { ProtocolClient, ProtocolRpcError } from "@rxycode/protocol-client";
import type { Subprocess } from "bun";
import { appendFileSync } from "node:fs";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import {
  questionInfoFromParams,
  questionResultFromReply,
  type QuestionReply,
} from "../questionInfo.ts";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamReduceState,
} from "../streamReducer.ts";
import type { Mode, StatusInfo } from "../types.ts";
import {
  httpSendCommand,
  type CommandResult,
} from "./httpAdmin.ts";
import { notifyToStreamEvent } from "./notifyToStreamEvent.ts";
import {
  raceWithAbort,
  shouldClearStreamingOnNotify,
  shouldClearStreamingOnUserCancel,
} from "./streamLifecycle.ts";
import {
  applyTokenUsageToStatus,
  parseStdioAdminCommand,
  statusFromModelsList,
  type ModelsListPayload,
} from "./stdioCommands.ts";
import { resolveChildTarget } from "../childNavigation.ts";
import type {
  ChatApiCallbacks,
  ChatTransport,
  ChildNavigationEntry,
  ChildNavigationResult,
  SubagentResult,
} from "./types.ts";

const DEFAULT_INIT_TIMEOUT_MS = 60_000;
const DEFAULT_SESSION_TIMEOUT_MS = 60_000;
let warmOnOpenStarted = false;

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
  cache_hit_tokens?: number;
  cache_hit_rate?: number;
  reporting_status?: string;
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
  private pendingQuestions = new Map<string, (reply: QuestionReply) => void>();
  private questionTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private activePromptAbort: AbortController | null = null;
  private activeCallbacks: ChatApiCallbacks | null = null;
  private childViewSessionId: string | null = null;

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

  private clearPendingQuestions(reply: QuestionReply = { cancelled: true }): void {
    for (const timer of this.questionTimers.values()) {
      clearTimeout(timer);
    }
    this.questionTimers.clear();
    for (const resolve of this.pendingQuestions.values()) {
      resolve(reply);
    }
    this.pendingQuestions.clear();
  }

  private resetSession(reason?: Error): void {
    this.clearPendingApprovals();
    this.clearPendingQuestions();
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
    this.childViewSessionId = null;
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
      const payload = (params ?? {}) as Record<string, unknown>;
      if (method === "question/request") {
        const info = questionInfoFromParams(payload);
        const reply = await new Promise<QuestionReply>((resolve) => {
          this.pendingQuestions.set(info.questionId, resolve);
          const timer = setTimeout(() => {
            if (!this.pendingQuestions.has(info.questionId)) return;
            this.questionTimers.delete(info.questionId);
            this.pendingQuestions.delete(info.questionId);
            resolve({ timedOut: true });
          }, 120_000);
          this.questionTimers.set(info.questionId, timer);
          this.activeCallbacks?.onQuestionRequest?.(info);
        });
        this.activeCallbacks?.onQuestionRequest?.(null);
        return questionResultFromReply(info.questionId, reply);
      }
      if (method !== "approval/request") {
        return {};
      }
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
        client_version: "1.3.0",
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

  isReady(): boolean {
    return this.client !== null && this.sessionId !== null;
  }

  async listModels(): Promise<ModelsListPayload> {
    const client = await this.ensureReady();
    return (await client.request<ModelsListPayload>("models/list", {})) as ModelsListPayload;
  }

  async fetchStatusSnapshot(): Promise<StatusInfo | null> {
    try {
      const listed = await this.listModels();
      this.lastStatus = statusFromModelsList(listed, this.lastStatus);
    } catch {
      // Keep lastStatus. Never fall back to HTTP /status (different process, always 0).
    }
    return this.lastStatus;
  }

  async switchModel(modelId: string): Promise<CommandResult> {
    const client = await this.ensureReady();
    const active = (await client.request<{
      ok?: boolean;
      id?: string;
      message?: string;
    }>("models/set_active", { id: modelId })) as {
      ok?: boolean;
      id?: string;
      message?: string;
    };
    if (!active?.ok) {
      const message = active?.message || `切换失败: ${modelId}`;
      return { ok: false, action: "error", error: message, message };
    }
    if (this.sessionId) {
      try {
        await client.request("session/set_model", {
          session_id: this.sessionId,
          model_id: modelId,
        });
      } catch {
        // Worker may still be warming; persisted active_model is enough.
      }
    }
    try {
      await this.fetchStatusSnapshot();
    } catch {
      this.lastStatus = { ...(this.lastStatus ?? {}), model: modelId };
    }
    return {
      ok: true,
      action: "model_changed",
      message: `已切换: ${modelId}`,
    };
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

  resolveQuestion(questionId: string, reply: QuestionReply): boolean {
    const resolve = this.pendingQuestions.get(questionId);
    if (!resolve) return false;
    const timer = this.questionTimers.get(questionId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.questionTimers.delete(questionId);
    }
    this.pendingQuestions.delete(questionId);
    resolve(reply);
    return true;
  }

  async interrupt(): Promise<void> {
    if (shouldClearStreamingOnUserCancel()) {
      this.activeCallbacks?.onStreaming(false);
      this.activeCallbacks?.onProgress?.("");
    }
    this.activePromptAbort?.abort();
    if (!this.sessionId) return;
    const sessionId = this.sessionId;
    void this.ensureReady()
      .then((client) => client.request("session/interrupt", { session_id: sessionId }))
      .catch(() => {
        // best-effort; UI already left Processing
      });
  }

  async invokeSubagent(agentId: string, prompt: string): Promise<SubagentResult> {
    const client = await this.ensureReady();
    const result = await client.request<SubagentResult>("agent/invoke", {
      agent_id: agentId,
      prompt,
      parent_session_id: this.sessionId ?? "",
    });
    return result;
  }

  async listChildSessions(): Promise<ChildNavigationEntry[]> {
    const client = await this.ensureReady();
    if (!this.sessionId) throw new Error("appserver session not ready");
    const result = await client.request<{ sessions?: ChildNavigationEntry[] }>(
      "child_sessions/list",
      { root_session_id: this.sessionId },
    );
    return result.sessions ?? [];
  }

  async openChildSession(target: string): Promise<ChildNavigationResult> {
    const children = await this.listChildSessions();
    const entry = resolveChildTarget(target, children);
    if (!entry) return { ok: false, message: `child session not found: ${target}` };
    if (!this.sessionId) return { ok: false, message: "appserver session not ready" };
    const replay = await (await this.ensureReady()).request<{
      events?: Array<Record<string, unknown>>
    }>("child_sessions/events", { root_session_id: this.sessionId, cursor: 0 });
    this.childViewSessionId = entry.session_id;
    return {
      ok: true,
      entry,
      events: (replay.events ?? []).filter((event) => event.session_id === entry.session_id),
      message: `opened child session ${entry.session_id}`,
    };
  }

  async openParentSession(): Promise<ChildNavigationResult> {
    if (this.childViewSessionId === null) {
      return { ok: false, message: "already at the parent session" };
    }
    const childId = this.childViewSessionId;
    this.childViewSessionId = null;
    return { ok: true, message: `returned to parent session ${this.sessionId ?? ""}`, entry: { session_id: childId } };
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
    callbacks.onProgress?.("收到，正在回复…");

    // FX7: draw the thought placeholder BEFORE ensureReady so the assistant
    // row is on screen while the worker boots (aligned with HTTP transport).
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

    try {
      const client = await this.ensureReady();
      if (signal?.aborted) {
        throw Object.assign(new Error("Aborted"), { name: "AbortError" });
      }
      if (!this.sessionId) {
        throw new Error("appserver session not ready");
      }
      callbacks.onProgress?.("");

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
        if (event?.type === "token_usage" || event?.type === "final") {
          this.lastStatus = applyTokenUsageToStatus(this.lastStatus, event);
          callbacks.onStatus(this.lastStatus);
        }
        if (!event) return;
        if (!sawStreamActivity) {
          sawStreamActivity = true;
          callbacks.onProgress?.("");
        }
        if (event.type === "progress" && !state.hasReasoning) {
          callbacks.onProgress?.(event.message || event.text || "Working...");
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
        const result = (await raceWithAbort(
          client.request<PromptResult>("session/prompt", {
            session_id: this.sessionId,
            text: content,
            mode,
            thinking_expanded: thinkingExpandedPref,
            timeout_seconds: 600,
          }),
          signal,
          abort.signal,
        )) as PromptResult;

        if (
          result.input_tokens != null ||
          result.output_tokens != null ||
          result.cache_hit_tokens != null
        ) {
          this.lastStatus = applyTokenUsageToStatus(this.lastStatus, result);
          callbacks.onStatus(this.lastStatus);
        }

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

        // 保留完整 status 快照（chat 结束后 finally 会刷新 models/list）。
        try {
          await this.fetchStatusSnapshot();
        } catch {
          // Keep lastStatus from token_usage / prompt result.
        }
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
      // FX7: the thought placeholder may already be on screen — settle it
      // so a startup failure never leaves a dangling "…" row.
      if (state.messages.some((m) => m.role === "thinking")) {
        callbacks.onMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === userMsg.id);
          if (idx < 0) return prev;
          return [...prev.slice(0, idx + 1), ...settleActiveMessages(state.messages)];
        });
      }
      if (signal?.aborted || (e as Error)?.name === "AbortError") {
        callbacks.onMessages((prev) => [
          ...prev,
          {
            id: newId("system"),
            role: "system",
            content: "Cancelled.",
            timestamp: Date.now(),
          },
        ]);
      } else {
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
      }
    } finally {
      callbacks.onStreaming(false);
      callbacks.onProgress?.("");
      try {
        const listed = await this.fetchStatusSnapshot();
        this.lastStatus = listed ?? this.lastStatus;
        callbacks.onStatus(this.lastStatus);
      } catch {
        callbacks.onStatus(this.lastStatus);
      }
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
    onStatus(await sharedSession.fetchStatusSnapshot());
  },

  async sendCommand(command: string): Promise<CommandResult> {
    const parsed = parseStdioAdminCommand(command);
    if (parsed.kind === "thinking") {
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
    if (parsed.kind === "model") {
      try {
        return await sharedSession.switchModel(parsed.modelId);
      } catch (e) {
        return {
          ok: false,
          action: "error",
          error: e instanceof Error ? e.message : String(e),
          message: e instanceof Error ? e.message : String(e),
        };
      }
    }
    return httpSendCommand(parsed.command);
  },

  async cancelActiveRequest(): Promise<void> {
    await sharedSession.interrupt();
  },

  async invokeSubagent(agentId: string, prompt: string): Promise<SubagentResult> {
    return sharedSession.invokeSubagent(agentId, prompt);
  },

  async listChildSessions(): Promise<ChildNavigationEntry[]> {
    return sharedSession.listChildSessions();
  },

  async openChildSession(target: string): Promise<ChildNavigationResult> {
    return sharedSession.openChildSession(target);
  },

  async openParentSession(): Promise<ChildNavigationResult> {
    return sharedSession.openParentSession();
  },

  async respondApproval(approvalId: string, decision: ApprovalDecision): Promise<boolean> {
    return sharedSession.resolveApproval(approvalId, decision);
  },

  async respondQuestion(questionId: string, reply: QuestionReply): Promise<boolean> {
    return sharedSession.resolveQuestion(questionId, reply);
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

/** Kick appserver spawn as soon as the OpenTUI process starts. */
export function startStdioWarmOnOpen(): void {
  if (warmOnOpenStarted) return;
  warmOnOpenStarted = true;
  void warmStdioBootstrap().catch(() => {
    // first prompt will bootstrap; ignore warm failures
  });
}

/** Configured models + persisted active id (no HTTP agent required). */
export async function listStdioModels(): Promise<ModelsListPayload> {
  return sharedSession.listModels();
}

export function isStdioSessionReady(): boolean {
  return sharedSession.isReady();
}

/** Test hook: reset shared stdio session between tests. */
export function __resetStdioSessionForTests(): void {
  void sharedSession.shutdown();
  sharedSession = new StdioAppserverSession();
  pythonCmdOverride = null;
  thinkingExpandedPref = false;
  warmOnOpenStarted = false;
}
