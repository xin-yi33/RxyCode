import { ProtocolClient, ProtocolRpcError } from "@rxycode/protocol-client";
import type { Subprocess } from "bun";
import { appendFileSync } from "node:fs";
import type { ApprovalDecision } from "../ApprovalDialog.tsx";
import {
  questionInfoFromParams,
  questionResultFromReply,
  type QuestionInfo,
  type QuestionReply,
} from "../questionInfo.ts";
import {
  applyStreamEvent,
  settleActiveMessages,
  type StreamReduceState,
} from "../streamReducer.ts";
import { applyTodoUpdated, snapshotFromTodoGet, type TodoDockSnapshot } from "../todoDock.ts";
import type { Mode, StatusInfo } from "../types.ts";
import {
  httpSendCommand,
  type CommandResult,
} from "./httpAdmin.ts";
import { applyThoughtExpandedOverride, nextThoughtExpanded, resetThinkingDisplay } from "../lib/thinkingDisplay.ts";
import { looksLikePlanDocument, parsePlanDoc } from "../planDoc.ts";
import { liveProgressText, notifyToStreamEvent, toolWaitText } from "./notifyToStreamEvent.ts";
import {
  composeTurnWithSteers,
  raceWithAbort,
  shouldClearStreamingOnNotify,
  shouldClearStreamingOnUserCancel,
  spliceTurnMessages,
  type SteerMark,
} from "./streamLifecycle.ts";
import {
  applyTokenUsageToStatus,
  parseStdioAdminCommand,
  statusFromModelsList,
  type ModelsListPayload,
} from "./stdioCommands.ts";
import { resolveChildTarget } from "../childNavigation.ts";
import type {
  AttachSessionResult,
  ChatApiCallbacks,
  ChatTransport,
  ChildNavigationEntry,
  ChildNavigationResult,
  SessionListRow,
  SteerTurnResult,
  SubagentResult,
} from "./types.ts";
import { sessionEventsToMessages } from "../dialog/sessionEventsToMessages.ts";
import { MAX_CLIPBOARD_ATTACHMENTS, type ClipboardAttachment } from "../clipboard.ts";
import type { PromptRequest } from "../../../protocol-client/src/generated/types.ts";

const DEFAULT_INIT_TIMEOUT_MS = 60_000;
const DEFAULT_SESSION_TIMEOUT_MS = 60_000;
// 2026-10-09 模型切换有界等待：对话框曾有「正在切换模型…」无限转圈（request 无超时）。
const MODEL_SET_ACTIVE_TIMEOUT_MS = 10_000;
const SESSION_SET_MODEL_TIMEOUT_MS = 40_000; // server agent_host 上限 30s + 余量
const STATUS_SNAPSHOT_TIMEOUT_MS = 5_000;
// 2026-10-11 /session 目录有界等待：原来 request 无超时，服务端静默丢应答时
// 会话对话框长转圈；超时直接交还 UI 错误态，不触发 respawn（与进程已死区分）。
const SESSIONS_LIST_TIMEOUT_MS = 8_000;
/** Bounded wait for catalog/admin reads. session/prompt stays unbounded. */
const DEFAULT_ADMIN_RPC_TIMEOUT_MS = 8_000;
let warmOnOpenStarted = false;

function newId(suffix: string): string {
  return `${Date.now()}-${suffix}-${Math.random().toString().slice(2, 7)}`;
}

/** Bound any promise without changing the callee's signature. */
function withBoundedWait<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_resolve, reject) => {
      setTimeout(() => reject(new Error(message)), ms);
    }),
  ]);
}

function initTimeoutMs(): number {
  const raw = Number(process.env.RXYCODE_APPSERVER_INIT_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_INIT_TIMEOUT_MS;
}

function sessionTimeoutMs(): number {
  const raw = Number(process.env.RXYCODE_APPSERVER_SESSION_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_SESSION_TIMEOUT_MS;
}

function adminRpcTimeoutMs(): number {
  const raw = Number(process.env.RXYCODE_ADMIN_RPC_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_ADMIN_RPC_TIMEOUT_MS;
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
  context_used?: number | null;
};

let pythonCmdOverride: string[] | null = null;
/** Survives session recreate (e.g. /model switch). */
let thinkingExpandedPref = false;

/** Test hook: override appserver spawn command. */
export function __setPythonCmdForTests(cmd: string[] | null): void {
  pythonCmdOverride = cmd;
}

export class StdioAppserverSession {
  private proc: Subprocess<"pipe", "pipe", "pipe"> | null = null;
  private client: ProtocolClient | null = null;
  private sessionId: string | null = null;
  private serverCapabilities: Record<string, unknown> = {};

  getCurrentSessionId(): string | null {
    return this.sessionId;
  }
  private ready: Promise<void> | null = null;
  private lastStatus: StatusInfo | null = null;
  private pendingApprovals = new Map<
    string,
    (decision: ApprovalDecision) => void
  >();
  private approvalTimers = new Map<string, ReturnType<typeof setTimeout>>();
  /** FIFO of approval request ids. The dialog shows only the head, so a second request cannot replace it. */
  private approvalQueue: string[] = [];
  private approvalInfo = new Map<string, {
    approvalId: string;
    tool: string;
    risk: string;
    args: string;
    description: string;
  }>();
  /** In-flight handleLine calls. The read pump does not await them: an approval wait must not stall later RPCs. */
  private lineJobs = new Set<Promise<void>>();
  /** Bumped to retire a connection writer before its pending replies run. */
  private writerGeneration = 0;
  private questionQueue: string[] = [];
  private questionInfo = new Map<string, QuestionInfo>();
  private pendingQuestions = new Map<string, (reply: QuestionReply) => void>();
  private activePromptAbort: AbortController | null = null;
  private activeCallbacks: ChatApiCallbacks | null = null;
  private promptEpoch = 0;
  private childViewSessionId: string | null = null;
  private lastProcessFailed: string | null = null;
  onTodo: ((snapshot: TodoDockSnapshot) => void) | null = null;
  private todoView: TodoDockSnapshot = { list_id: "default", revision: 0, items: [] };
  private todoTicket = 0;
  /** Worker model label. Set when a session switch fails so polls do not show the new global default. */
  /** Config id of the open task's model. Display text is derived from this id. */
  private sessionModelId: string | null = null;
  /** Bumped on every attach so a slower older load cannot commit a newer session. */
  private attachGeneration = 0;
  private steerMarks: SteerMark[] = [];
  private liveTurn: {
    epoch: number;
    mode: Mode;
    getState: () => StreamReduceState;
    publish: (next: StreamReduceState) => void;
  } | null = null;

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

  private emitApprovalHead(): void {
    const head = this.approvalQueue[0];
    if (!head) {
      this.activeCallbacks?.onApprovalRequest?.(null);
      return;
    }
    const info = this.approvalInfo.get(head);
    if (info) this.activeCallbacks?.onApprovalRequest?.(info);
  }

  private enqueueApproval(info: {
    approvalId: string;
    tool: string;
    risk: string;
    args: string;
    description: string;
  }): void {
    this.approvalInfo.set(info.approvalId, info);
    if (!this.approvalQueue.includes(info.approvalId)) this.approvalQueue.push(info.approvalId);
    if (this.approvalQueue[0] === info.approvalId) this.emitApprovalHead();
  }

  private settleApproval(requestId: string): void {
    this.approvalQueue = this.approvalQueue.filter((id) => id !== requestId);
    this.approvalInfo.delete(requestId);
    this.emitApprovalHead();
  }

  private clearPendingApprovals(decision: ApprovalDecision = "rejected"): void {
    for (const timer of this.approvalTimers.values()) {
      clearTimeout(timer);
    }
    this.approvalTimers.clear();
    this.approvalQueue = [];
    this.approvalInfo?.clear();
    const pending = [...this.pendingApprovals.values()];
    this.pendingApprovals.clear();
    this.activeCallbacks?.onApprovalRequest?.(null);
    for (const resolve of pending) resolve(decision);
  }

  /** Parse one stdout line without waiting for a human approval inside it. */
  private pumpLine(line: string): void {
    const client = this.client;
    if (!client) return;
    let job: Promise<void> = Promise.resolve();
    job = client.handleLine(line).catch(() => {
      // handleLine reports RPC errors itself. A rejection must not stop the read pump.
    }).finally(() => {
      this.lineJobs.delete(job);
    });
    this.lineJobs.add(job);
  }

  private emitQuestionHead(): void {
    const head = this.questionQueue[0];
    if (!head) {
      this.activeCallbacks?.onQuestionRequest?.(null);
      return;
    }
    const info = this.questionInfo.get(head);
    if (info) this.activeCallbacks?.onQuestionRequest?.(info);
  }

  private enqueueQuestion(info: QuestionInfo): void {
    this.questionInfo.set(info.questionId, info);
    if (!this.questionQueue.includes(info.questionId)) this.questionQueue.push(info.questionId);
    if (this.questionQueue[0] === info.questionId) this.emitQuestionHead();
  }

  private settleQuestion(questionId: string): void {
    this.questionQueue = this.questionQueue.filter((id) => id !== questionId);
    this.questionInfo.delete(questionId);
    this.emitQuestionHead();
  }

  private clearPendingQuestions(reply: QuestionReply = { cancelled: true }): void {
    this.questionQueue = [];
    this.questionInfo?.clear();
    const pending = [...(this.pendingQuestions?.values() ?? [])];
    this.pendingQuestions?.clear();
    this.activeCallbacks?.onQuestionRequest?.(null);
    for (const resolve of pending) resolve(reply);
  }

  /** Drop this connection's writer so a late approval reply cannot hit a dead pipe or the next process. */
  private invalidateWriter(): void {
    this.writerGeneration += 1;
  }

  private resetSession(reason?: Error): void {
    this.invalidateWriter();
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
    this.serverCapabilities = {};
    this.sessionModelId = null;
    this.forgetTodoView();
    this.childViewSessionId = null;
    this.ready = null;
    this.lastProcessFailed = null;
  }

  private closedError(fallback: string): Error {
    const reason = this.lastProcessFailed?.trim();
    return new Error(reason || fallback);
  }

  private appserverAlive(): boolean {
    const proc = this.proc;
    if (!this.client || !proc) return false;
    return proc.exitCode === null;
  }

  async ensureReady(): Promise<ProtocolClient> {
    if (this.ready) {
      try {
        await this.ready;
      } catch (err) {
        this.resetSession(err instanceof Error ? err : new Error(String(err)));
      }
    }
    // A dead child used to stay dead: /session then rendered
    // "appserver stdout closed" and an empty list, while tasks.json
    // was still on disk.
    if (!this.appserverAlive()) {
      this.resetSession();
      this.ready = this.start();
      try {
        await this.ready;
      } catch (err) {
        this.resetSession(err instanceof Error ? err : new Error(String(err)));
        throw err;
      }
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
      // 每个窗口一个 stdio appserver。不要抢同一把 data-dir 锁。
      RXYCODE_APPSERVER_MULTI: "1",
      RXYCODE_APPSERVER_PREEMPT: "0",
      // 废弃代码（2026-09-22）：默认抢锁，45 秒内第二扇窗口启动失败。
      // RXYCODE_APPSERVER_PREEMPT: process.env.RXYCODE_APPSERVER_PREEMPT ?? "1",
    };
    if (process.env.RXYCODE_APPSERVER_STUB === "1") {
      env.RXYCODE_APPSERVER_STUB = "1";
    }
    this.lastProcessFailed = null;

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
    const generation = ++this.writerGeneration;
    const proc = this.proc;
    const client = new ProtocolClient((line) => {
      // A closed generation must not write. A live write error is recorded and rethrown.
      if (
        generation !== this.writerGeneration ||
        !proc ||
        this.proc !== proc ||
        proc.exitCode !== null
      ) {
        return;
      }
      try {
        stdin.write(encoder.encode(`${line}\n`));
      } catch (err) {
        this.writerGeneration += 1;
        const message = err instanceof Error ? err.message : String(err);
        this.lastProcessFailed = message;
        throw err;
      }
    });
    this.client = client;
    client.onNotification = (method, params) => {
      if (method !== "event/todo_updated") return;
      const snapshot = (params as { snapshot?: unknown } | null)?.snapshot;
      if (snapshot) this.publishTodo(snapshot);
    };

    client.onServerRequest = async (method, params) => {
      const payload = (params ?? {}) as Record<string, unknown>;
      if (method === "question/request") {
        const info = questionInfoFromParams(payload);
        // question 等用户回答，永不自动超时提交空答案（approval 的 120s
        // 超时不适用于 question；后端同样不限时）。
        const reply = await new Promise<QuestionReply>((resolve) => {
          this.pendingQuestions.set(info.questionId, resolve);
          this.enqueueQuestion(info);
        });
        this.settleQuestion(info.questionId);
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
        this.enqueueApproval({
          approvalId: requestId,
          tool: String(payload.action ?? "unknown"),
          risk: String(payload.risk_level ?? "WRITE"),
          args:
            typeof argsRaw === "string"
              ? argsRaw
              : JSON.stringify(argsRaw ?? details ?? {}),
          description:
            // 2026-10-12 审批界面回显外部（如 MCP）工具描述，用户复核可见。
            typeof details?.description === "string" ? details.description : "",
        });
      });
      this.settleApproval(requestId);
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
            client.rejectAllPending(this.closedError("appserver stdout closed"));
            this.resetSession(this.closedError("appserver stdout closed"));
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          let newline = buffer.indexOf("\n");
          while (newline >= 0) {
            const line = buffer.slice(0, newline);
            buffer = buffer.slice(newline + 1);
            this.pumpLine(line);
            newline = buffer.indexOf("\n");
          }
        }
        if (buffer.trim()) {
          this.pumpLine(buffer);
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
      client.rejectAllPending(this.closedError(`appserver exited (${exitCode})`));
      if (this.proc === proc) {
        this.resetSession(this.closedError(`appserver exited (${exitCode})`));
      }
    })();

    const initialized = await client.requestWithTimeout<{ capabilities?: Record<string, unknown> }>(
      "initialize",
      {
        client_name: "opentui",
        client_version: "1.4.3",
        protocol_version: "1.0.0",
      },
      initTimeoutMs(),
    ) as { capabilities?: Record<string, unknown> };
    this.serverCapabilities = initialized?.capabilities && typeof initialized.capabilities === "object"
      ? initialized.capabilities
      : {};
    const session = (await client.requestWithTimeout<{ session_id: string; model_id?: string | null }>(
      "session/new",
      { workspace_root: this.workspaceRoot() },
      sessionTimeoutMs(),
    )) as { session_id: string; model_id?: string | null };
    this.sessionId = session.session_id;
    this.sessionModelId = session.model_id ?? null;
    void this.refreshTodo().catch(() => {});
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

  /** Coalesced models/list read — see listModels(). */
  private inflightModelsList: Promise<ModelsListPayload> | null = null;

  async listModels(): Promise<ModelsListPayload> {
    // /model 切换成功后 fetchStatus() 与 fetchModels() 同拍触发同一 RPC
    //（一个读状态一个读目录，数据都是 models/list）：合并 in-flight 读，
    // 一次请求结果复用，不再串行重发。
    if (this.inflightModelsList) return this.inflightModelsList;
    const pending = (async () => {
      const client = await this.ensureReady();
      return (await client.requestWithTimeout<ModelsListPayload>(
        "models/list",
        {},
        adminRpcTimeoutMs(),
      )) as ModelsListPayload;
    })();
    this.inflightModelsList = pending;
    pending
      .catch(() => {})
      .finally(() => {
        if (this.inflightModelsList === pending) this.inflightModelsList = null;
      });
    return pending;
  }

  async fetchStatusSnapshot(): Promise<StatusInfo | null> {
    try {
      const listed = await this.listModels();
      const taskModelId = this.sessionModelId || undefined;
      this.lastStatus = statusFromModelsList(listed, this.lastStatus, taskModelId);
      if (this.sessionId && !this.sessionModelId) {
        const adopted =
          listed.active || listed.models?.find((item) => item.active)?.id || "";
        if (adopted) this.sessionModelId = adopted;
      }
    } catch {
      // Keep lastStatus. Never fall back to HTTP /status (different process, always 0).
    }
    return this.lastStatus;
  }

  async switchModel(modelId: string): Promise<CommandResult> {
    // 2026-10-09 修复：三处 RPC 原来走无超时的 client.request——服务端一旦
    // 静默丢应答，对话框就永远停在「正在切换模型…」，后续点击被 switching
    // 门拦死（用户实测）。全部改为有界等待，超时者落为「切换失败」。
    const client = await this.ensureReady();
    // Captured before any await that can outlive this screen. Later reads of
    // this.sessionId would aim session/set_model at whatever session loaded
    // while models/set_active was still in flight.
    const targetSessionId = this.sessionId;
    const previousModelId = this.sessionModelId;
    const generation = this.attachGeneration;
    const stillThisSession = () =>
      this.attachGeneration === generation && this.sessionId === targetSessionId;
    const active = (await client.requestWithTimeout<{
      ok?: boolean;
      id?: string;
      message?: string;
    }>("models/set_active", { id: modelId }, MODEL_SET_ACTIVE_TIMEOUT_MS)) as {
      ok?: boolean;
      id?: string;
      message?: string;
    };
    if (!active?.ok) {
      const message = active?.message || `切换失败: ${modelId}`;
      return { ok: false, action: "error", error: message, message };
    }
    let sessionSet: "ok" | "skipped" | "error" = "skipped";
    let sessionErr = "";
    if (targetSessionId) {
      try {
        await client.requestWithTimeout(
          "session/set_model",
          { session_id: targetSessionId, model_id: modelId },
          // server 侧 agent_host 自带 30s 上限，客户端留余量先收错误。
          SESSION_SET_MODEL_TIMEOUT_MS,
        );
        sessionSet = "ok";
        if (stillThisSession()) this.sessionModelId = modelId;
      } catch (e) {
        sessionSet = "error";
        sessionErr = e instanceof Error ? e.message : String(e);
        if (stillThisSession()) this.sessionModelId = previousModelId;
      }
    }
    if (!stillThisSession()) {
      return {
        ok: false,
        action: "error",
        error: "会话已更换",
        message: "会话已更换",
      };
    }
    if (sessionSet === "error") {
      // 2026-10-11 假成功修复：全局 active 已持久化但 worker 还跑旧模型——
      // 不得返回 model_changed；调用方对话框据此提示「切换失败，请重试」。
      // 同时不刷新状态快照，芯片继续显示 worker 实际在用的旧模型。
      // （无 session 时 ② 为 skipped：全局默认模型已切，仍算成功。）
      const message = sessionErr ? `${sessionErr}，请重试` : "切换失败，请重试";
      return { ok: false, action: "error", error: message, message };
    }
    try {
      await withBoundedWait(
        this.fetchStatusSnapshot(),
        STATUS_SNAPSHOT_TIMEOUT_MS,
        "status refresh timed out",
      );
    } catch {
      // session/set_model already succeeded, so the id is confirmed. The
      // catalog read did not return a nickname; show the id rather than a
      // name that was not looked up.
      if (stillThisSession()) {
        this.lastStatus = { ...(this.lastStatus ?? {}), model: modelId };
      }
    }
    if (!stillThisSession()) {
      return {
        ok: false,
        action: "error",
        error: "会话已更换",
        message: "会话已更换",
      };
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
    const result = (await client.requestWithTimeout("session/set_thinking_expanded", {
      session_id: this.sessionId,
      expanded,
    }, adminRpcTimeoutMs())) as {
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
    this.pendingQuestions.delete(questionId);
    resolve(reply);
    return true;
  }

  async interrupt(): Promise<void> {
    this.clearPendingApprovals("rejected");
    this.clearPendingQuestions({ cancelled: true });
    if (shouldClearStreamingOnUserCancel()) {
      this.activeCallbacks?.onStreaming(false);
      this.activeCallbacks?.onProgress?.("");
    }
    this.activePromptAbort?.abort();
    if (!this.sessionId) return;
    const sessionId = this.sessionId;
    void this.ensureReady()
      .then((client) =>
        client.requestWithTimeout(
          "session/interrupt",
          { session_id: sessionId },
          adminRpcTimeoutMs(),
        ),
      )
      .catch(() => {
        // best-effort; UI already left Processing
      });
  }

  async steerTurn(text: string, mode?: Mode): Promise<SteerTurnResult> {
    const trimmed = text.trim();
    if (!trimmed) return { ok: false, message: "空内容无法立即发送" };
    if (!this.sessionId) return { ok: false, message: "会话未就绪" };
    const sessionId = this.sessionId;
    try {
      const client = await this.ensureReady();
      await client.requestWithTimeout(
        "turn/steer",
        { session_id: sessionId, text: trimmed },
        adminRpcTimeoutMs(),
      );
      const live = this.liveTurn;
      if (live && this.promptEpoch === live.epoch) {
        const at = live.getState().messages.length;
        this.steerMarks.push({
          at,
          msg: {
            id: newId("user"),
            role: "user",
            content: trimmed,
            timestamp: Date.now(),
            mode: mode ?? live.mode,
          },
        });
        live.publish(live.getState());
        return { ok: true, injected: true };
      }
      return { ok: true, injected: false };
    } catch (e) {
      return { ok: false, message: e instanceof Error ? e.message : String(e) };
    }
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
    displayContent?: string,
    attachments?: readonly ClipboardAttachment[],
  ): Promise<void> {
    if (attachments?.length) {
      if (attachments.length > MAX_CLIPBOARD_ATTACHMENTS) {
        throw new Error(`附件最多 ${MAX_CLIPBOARD_ATTACHMENTS} 个；未发送`);
      }
      await this.ensureReady();
      if (this.serverCapabilities.prompt_attachments !== true) {
        throw new Error("当前 appserver 未声明 prompt_attachments 能力；请重启/更新 server 后再发送，附件草稿已保留");
      }
    }
    const userMsg = {
      id: newId("user"),
      role: "user" as const,
      content: displayContent?.trim() ? displayContent : content,
      timestamp: Date.now(),
      mode,
      ...(attachments?.length ? { attachments: attachments.map((item) => ({ ...item })) } : {}),
    };
    this.promptEpoch += 1;
    const epoch = this.promptEpoch;
    const turnRequestId = newId("turn");
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
          expanded: nextThoughtExpanded(),
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
      if (this.promptEpoch !== epoch) {
        return;
      }
      state = {
        ...next,
        messages: next.messages.map(applyThoughtExpandedOverride),
      };
      const composed = composeTurnWithSteers(state.messages, this.steerMarks);
      callbacks.onMessages((prev) => spliceTurnMessages(prev, userMsg.id, composed));
    };
    this.steerMarks = [];
    this.liveTurn = { epoch, mode, getState: () => state, publish };

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
      let lastLiveProgress = "";
      let streamingCleared = false;
      let streamOutChars = 0;
      const baselineUsed = Math.round((this.lastStatus?.context_used_k ?? 0) * 1000);
      const publishLiveUsage = () => {
        const est = Math.max(baselineUsed, 0) + Math.ceil(streamOutChars / 4);
        if (est <= 0) return;
        this.lastStatus = applyTokenUsageToStatus(this.lastStatus, {
          reporting_status: "partial",
          context_used: est,
        });
        callbacks.onStatus(this.lastStatus);
      };
      const clearStreamingEarly = () => {
        if (streamingCleared) return;
        streamingCleared = true;
        callbacks.onStreaming(false);
        callbacks.onProgress?.("");
      };
      client.onNotification = (method, params) => {
        priorOnNotification?.(method, params);
        if (this.promptEpoch !== epoch) return;
        const event = notifyToStreamEvent(method, params);
        if (event?.type === "token_usage" || event?.type === "final") {
          this.lastStatus = applyTokenUsageToStatus(this.lastStatus, event);
          callbacks.onStatus(this.lastStatus);
        }
        if (event?.type === "plan") {
          callbacks.onPlan?.(parsePlanDoc(String(event.text || ""), event.steps));
        }
        if (event?.type === "token" || event?.type === "reasoning") {
          streamOutChars += String(event.text || event.thinking || "").length;
          if (streamOutChars > 0 && streamOutChars % 200 < 24) {
            publishLiveUsage();
          }
        }
        if (!event) return;
        if (!sawStreamActivity) {
          sawStreamActivity = true;
          callbacks.onProgress?.("");
        }
        const live = liveProgressText(event);
        if (live && live !== lastLiveProgress && event.type !== "tool_call") {
          lastLiveProgress = live;
          callbacks.onProgress?.(live);
        }
        const next = applyStreamEvent(state, event, newId);
        if (event.type === "tool_call" || event.type === "tool_result") {
          const running = next.messages.filter(
            (m) => m.role === "tool" && m.toolStatus === "running",
          );
          if (running.length) {
            const wait = toolWaitText(running[0].toolName || "tool");
            lastLiveProgress = wait;
            callbacks.onProgress?.(wait);
          } else {
            lastLiveProgress = "";
            callbacks.onProgress?.("");
          }
          if (event.type === "tool_result" && this.pendingApprovals.size === 0 && this.approvalQueue.length === 0) {
            callbacks.onApprovalRequest?.(null);
          }
        }
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
        const promptAttachments = attachments?.length
          ? attachments.map((item) => ({ ...item })) as PromptRequest["attachments"]
          : undefined;
        const promptParams = {
          session_id: this.sessionId,
          text: content,
          mode,
          thinking_expanded: thinkingExpandedPref,
          request_id: turnRequestId,
          ...(promptAttachments ? { attachments: promptAttachments } : {}),
        } satisfies PromptRequest;
        const result = (await raceWithAbort(
          client.request<PromptResult>("session/prompt", promptParams),
          signal,
          abort.signal,
        )) as PromptResult;

        if (
          result.input_tokens != null ||
          result.output_tokens != null ||
          result.cache_hit_tokens != null ||
          result.context_used != null
        ) {
          this.lastStatus = applyTokenUsageToStatus(this.lastStatus, result);
          callbacks.onStatus(this.lastStatus);
        }

        if (!state.hasReasoning && result.thinking?.trim()) {
          publish(
            applyStreamEvent(
              state,
              { type: "reasoning", thinking: result.thinking },
              newId,
            ),
          );
        }
        if (result.text) {
          const finalEvent = applyStreamEvent(
            state,
            { type: "final", text: result.text, thinking: result.thinking },
            newId,
          );
          publish(finalEvent);
          if (mode === "plan" && looksLikePlanDocument(result.text)) {
            callbacks.onPlan?.(parsePlanDoc(result.text));
          }
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
        if (attachments?.length) throw e;
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
        if (this.promptEpoch === epoch) {
          client.onNotification = priorOnNotification;
        }
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
      if (attachments?.length) throw e;
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
      if (this.liveTurn?.epoch === epoch) this.liveTurn = null;
      this.steerMarks = [];
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
    const client = this.client;
    // Answer queued approvals and questions while this writer is still the live one.
    this.clearPendingApprovals("rejected");
    this.clearPendingQuestions({ cancelled: true });
    const jobs = [...this.lineJobs];
    if (jobs.length > 0) await Promise.allSettled(jobs);
    try {
      if (this.client === client) {
        await client.request("shutdown", { reason: "opentui exit" });
      }
    } catch {
      // ignore
    }
    if (this.client === client) this.resetSession();
  }

  private async requestSessionList(timeoutMs: number): Promise<SessionListRow[]> {
    const client = await this.ensureReady();
    const listed = (await client.requestWithTimeout<{ sessions?: SessionListRow[] }>(
      "sessions/list",
      {},
      timeoutMs,
    )) as { sessions?: SessionListRow[] };
    return Array.isArray(listed.sessions) ? listed.sessions : [];
  }

  async listSessions(timeoutMs = SESSIONS_LIST_TIMEOUT_MS): Promise<SessionListRow[]> {
    try {
      return await this.requestSessionList(timeoutMs);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // RPC 超时（服务端静默丢应答）直接交还 UI 错误态；只有 appserver 进程
      // 已死（stdout closed / exited）才 reset + respawn 并重试一次。
      if (!message.includes("appserver stdout closed") && !message.includes("appserver exited")) {
        throw err;
      }
      this.resetSession(err instanceof Error ? err : new Error(message));
      return await this.requestSessionList(timeoutMs);
    }
  }

  async attachSession(sessionId: string, modelId?: string | null): Promise<AttachSessionResult> {
    const client = await this.ensureReady();
    const generation = (this.attachGeneration ?? 0) + 1;
    this.attachGeneration = generation;
    const previousId = this.sessionId;
    if (previousId && previousId !== sessionId) {
      try {
        await this.interrupt();
      } catch {
        // switching away from a live turn is best-effort
      }
    }
    if (generation !== this.attachGeneration) {
      throw new Error("stale session attach");
    }
    const timeout = adminRpcTimeoutMs();
    let replay = (await client.requestWithTimeout<{
      events?: Array<{ method?: string; params?: Record<string, unknown> }>;
      gap_detected?: boolean;
    }>("session/events", { session_id: sessionId, cursor: 0 }, timeout)) as {
      events?: Array<{ method?: string; params?: Record<string, unknown> }>;
      gap_detected?: boolean;
    };
    if (replay.gap_detected) {
      replay = (await client.requestWithTimeout("session/events", {
        session_id: sessionId,
        cursor: 0,
      }, timeout)) as typeof replay;
    }
    if (generation !== this.attachGeneration) {
      throw new Error("stale session attach");
    }
    if (previousId !== sessionId) this.forgetTodoView();
    this.sessionId = sessionId;
    this.sessionModelId = modelId || null;
    void this.refreshTodo().catch(() => {});
    void this.warmBootstrap().catch(() => {
      // first prompt will bootstrap
    });
    return {
      session_id: sessionId,
      messages: sessionEventsToMessages(replay.events || []),
    };
  }

  async renameSession(sessionId: string, title: string): Promise<SessionListRow> {
    const client = await this.ensureReady();
    return (await client.requestWithTimeout<SessionListRow>(
      "session/rename",
      { session_id: sessionId, title },
      adminRpcTimeoutMs(),
    )) as SessionListRow;
  }

  async trashSession(sessionId: string): Promise<void> {
    const client = await this.ensureReady();
    await client.requestWithTimeout(
      "session/trash",
      { session_id: sessionId },
      adminRpcTimeoutMs(),
    );
    if (this.sessionId === sessionId) {
      const created = await client.request<{ session_id: string; model_id?: string | null }>("session/new", {
        workspace_root: this.workspaceRoot(),
      });
      this.sessionId = created.session_id;
      this.sessionModelId = created.model_id ?? null;
      this.forgetTodoView();
      void this.refreshTodo().catch(() => {});
    }
  }

  async pinSession(sessionId: string, pinned: boolean): Promise<void> {
    const client = await this.ensureReady();
    await client.requestWithTimeout("thread/pin", {
      session_id: sessionId,
      thread_id: sessionId,
      pinned,
    }, adminRpcTimeoutMs());
  }

  private forgetTodoView(): void {
    this.todoTicket += 1;
    this.todoView = { list_id: "default", revision: 0, items: [] };
    this.onTodo?.(this.todoView);
  }

  publishTodo(payload: unknown): void {
    const raw = (payload ?? {}) as { session_id?: string; list_id?: string };
    const owner = String(raw.session_id || "");
    // 没有当前会话时 dock 不属于任何人。reset 之后迟到的旧快照不能再填回来。
    if (!this.sessionId) return;
    if (owner && owner !== this.sessionId) return;
    const listId = String(raw.list_id || "");
    if (listId && this.todoView.revision > 0 && listId !== this.todoView.list_id) return;
    const next = applyTodoUpdated(this.todoView, { snapshot: snapshotFromTodoGet(payload) });
    if (next === this.todoView) return;
    this.todoView = next;
    this.onTodo?.(next);
  }

  async refreshTodo(): Promise<void> {
    if (!this.client || !this.sessionId) return;
    const sessionId = this.sessionId;
    const ticket = ++this.todoTicket;
    const result = (await this.client.requestWithTimeout(
      "todo/get",
      { session_id: sessionId },
      adminRpcTimeoutMs(),
    )) as {
      session_id?: string;
    };
    if (ticket !== this.todoTicket || sessionId !== this.sessionId) return;
    this.publishTodo({ ...result, session_id: result.session_id || sessionId });
  }

  async forkSession(sessionId: string): Promise<SessionListRow> {
    const client = await this.ensureReady();
    return (await client.request<SessionListRow>("session/fork", {
      session_id: sessionId,
    })) as SessionListRow;
  }
}

let sharedSession = new StdioAppserverSession();

export const stdioTransport: ChatTransport = {
  kind: "stdio",

  getCurrentSessionId() {
    return sharedSession.getCurrentSessionId();
  },

  async fetchStatus(onStatus: (status: StatusInfo | null) => void): Promise<void> {
    onStatus(await sharedSession.fetchStatusSnapshot());
  },

  async sendCommand(command: string): Promise<CommandResult> {
    const parsed = parseStdioAdminCommand(command);
    if (parsed.kind === "thinking") {
      const { cycleThinkingDisplay } = await import("../lib/thinkingDisplay.ts");
      const result = cycleThinkingDisplay();
      return {
        ok: true,
        action: "thinking_toggled",
        message: "思考过程: " + (result.expanded ? "展开" : "折叠"),
        expanded: result.expanded,
      };
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
    const raw = String(parsed.command || command).trim();
    if (/^\/(session|save-chat|load-chat|list-chats)(\s|$)/.test(raw)) {
      return {
        ok: true,
        action: "session_auto",
        message: "会话已自动保存，请用 /session 打开列表",
      };
    }
    return httpSendCommand(parsed.command);
  },

  async cancelActiveRequest(): Promise<void> {
    await sharedSession.interrupt();
  },

  async steerTurn(text: string) {
    return sharedSession.steerTurn(text);
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
    displayContent?: string,
    attachments?: readonly ClipboardAttachment[],
  ): Promise<void> {
    await sharedSession.sendChatMessage(content, mode, callbacks, signal, displayContent, attachments);
  },

  async listSessions() {
    return sharedSession.listSessions();
  },

  async attachSession(sessionId: string, modelId?: string | null) {
    return sharedSession.attachSession(sessionId, modelId);
  },

  async renameSession(sessionId: string, title: string) {
    return sharedSession.renameSession(sessionId, title);
  },

  async trashSession(sessionId: string) {
    return sharedSession.trashSession(sessionId);
  },

  async pinSession(sessionId: string, pinned: boolean) {
    return sharedSession.pinSession(sessionId, pinned);
  },

  async forkSession(sessionId: string) {
    return sharedSession.forkSession(sessionId);
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
export function bindTodoDock(listener: (snapshot: TodoDockSnapshot) => void): () => void {
  sharedSession.onTodo = listener;
  void sharedSession.refreshTodo().catch(() => {});
  return () => {
    if (sharedSession.onTodo === listener) sharedSession.onTodo = null;
  };
}

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
  resetThinkingDisplay();
  warmOnOpenStarted = false;
}
