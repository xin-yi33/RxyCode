// 自动反馈询问 —— 纯决策模块（零依赖，便于 bun test）。
// 打分表（PRD 固定权重，勿自行调整）：
//   failed / recovery_required                       +3  run_failed
//   succeeded 且 final 文本为空                       +3  empty_answer
//   toolFailures >= 3                                 +1  tool_failures
//   用户停止且 run 时长 >= 20s                         +1.5 user_stopped
//   leaseEpochs >= 2（worker 掉线续接）                +1  worker_retry
//   180s 内后续消息：
//     与上一条 prompt 的字符 bigram Dice >= 0.8        +2  repeated_prompt
//     强抱怨词命中                                     +2  negative_followup
//     否则弱抱怨词命中                                 +1  negative_followup（强弱只取一个）
//     上一 run 也命中过 negative_followup              +1.5 repeated_dissatisfaction
// 阈值 score >= 3 才成为候选；门见 AutoPromptPolicy。

export type RunTerminalSignal = {
  runId: string
  sessionId: string
  status: string // 终态：succeeded|failed|cancelled|recovery_required
  finalText: string
  toolFailures: number
  stoppedByUser: boolean // 用户点了停止（cancel_requested→cancelled）
  durationMs: number
  leaseEpochs: number
  prompt: string // run 的用户消息（相似度基准）
  live: boolean // 本页面会话实时观察到进入终态（历史回放=false）
}

export type PromptScore = {
  score: number
  reasons: string[]
  negativeFollowup: boolean
}

export const PROMPT_THRESHOLD = 3
export const FOLLOWUP_WINDOW_MS = 180_000
export const PROMPT_DELAY_MS = 1_500
export const RESHOW_INTERVAL_MS = 30 * 60_000
export const DISMISS_COOLDOWN_MS = 24 * 3600_000
export const DISMISS_STREAK_LIMIT = 2
export const SESSION_DAILY_LIMIT = 2
export const ASKED_RUN_CAP = 200
export const AUTO_HIDE_MS = 20_000
export const STORAGE_KEY = "rxy.feedback.autoPrompt"
export const STORAGE_ASKED = "rxy.feedback.askedRuns"
export const STORAGE_STATE = "rxy.feedback.autoPromptState"

const STRONG_NEGATIVE =
  /还是不行|又错了|完全不对|根本没|没用|胡说|乱写|答非所问|不是我要的|still wrong|doesn't work|not working|useless/i
const WEAK_NEGATIVE = /不对|错了|不是|重新|wrong|again/i

export const REASON_TEXT: Record<string, string> = {
  run_failed: "任务失败",
  empty_answer: "回答为空",
  tool_failures: "多次工具失败",
  user_stopped: "你停止了任务",
  worker_retry: "运行中断过",
  repeated_prompt: "重复提问",
  negative_followup: "后续表示不满",
  repeated_dissatisfaction: "连续不满",
}

function normalizeText(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, " ")
}

function bigrams(text: string): Set<string> {
  const chars = normalizeText(text).replace(/\s/g, "")
  const grams = new Set<string>()
  for (let i = 0; i + 1 < chars.length; i += 1) grams.add(chars.slice(i, i + 2))
  if (chars.length === 1) grams.add(chars)
  return grams
}

// 字符 bigram Dice 相似度；空串与空串视为 0（无从判断）。
export function textSimilarity(a: string, b: string): number {
  const ga = bigrams(a)
  const gb = bigrams(b)
  if (ga.size === 0 || gb.size === 0) return 0
  let shared = 0
  for (const gram of ga) if (gb.has(gram)) shared += 1
  return (2 * shared) / (ga.size + gb.size)
}

export function scoreTerminalRun(
  signal: RunTerminalSignal,
  followup: { text: string; elapsedMs: number } | null,
  previousNegativeFollowup: boolean,
): PromptScore {
  let score = 0
  const reasons: string[] = []
  const add = (points: number, reason: string) => {
    score += points
    reasons.push(reason)
  }

  if (signal.status === "failed" || signal.status === "recovery_required") {
    add(3, "run_failed")
  }
  if (signal.status === "succeeded" && signal.finalText.length === 0) {
    add(3, "empty_answer")
  }
  if (signal.toolFailures >= 3) add(1, "tool_failures")
  if (signal.stoppedByUser && signal.durationMs >= 20_000) add(1.5, "user_stopped")
  if (signal.leaseEpochs >= 2) add(1, "worker_retry")

  let negative = false
  if (followup && followup.elapsedMs <= FOLLOWUP_WINDOW_MS) {
    if (textSimilarity(signal.prompt, followup.text) >= 0.8) {
      add(2, "repeated_prompt")
    }
    if (STRONG_NEGATIVE.test(followup.text)) {
      negative = true
      add(2, "negative_followup")
    } else if (WEAK_NEGATIVE.test(followup.text)) {
      negative = true
      add(1, "negative_followup")
    }
    if (negative && previousNegativeFollowup) {
      add(1.5, "repeated_dissatisfaction")
    }
  }
  return { score, reasons, negativeFollowup: negative }
}

export type StoredState = {
  lastShownAt: number | null // null = 从未展示（不能用 0 —— 会被当成“刚刚展示”）
  dismissStreak: number
  cooldownUntil: number
  // 每会话当天计数：{"<sessionId>": {"<YYYY-MM-DD>": n}}
  sessionDaily: Record<string, Record<string, number>>
}

export type GateContext = {
  enabled: boolean
  visible: boolean
  composerEmpty: boolean
  composerFocusedWithinMs: number | null // null = 从未聚焦
  modalOpen: boolean
}

export type PromptEvent =
  | { kind: "none" }
  | { kind: "show"; runId: string; sessionId: string; reasons: string[] }
  | { kind: "scheduled"; runId: string; sessionId: string; reasons: string[]; delayMs: number }
  | { kind: "cancelled"; runId: string }

type Candidate = {
  signal: RunTerminalSignal
  terminalAt: number
  best: PromptScore
  // 候选创建时快照「上一 run 是否有 negative_followup」——打分只用它，
  // 防止本候选自己的 negative 在重评时被当成“上一 run”自引用加分。
  previousNegative: boolean
  // 本候选是否命中过 negative_followup；只在候选结束时提交到 map。
  negativeFollowup: boolean
  followup: { text: string; elapsedMs: number } | null
}

function dayKey(now: number): string {
  return new Date(now).toISOString().slice(0, 10)
}

/**
 * 状态机：终态进入 → 评分（后续消息可在 180s 窗内多次补充重评）→
 * 全部门通过后延迟 1500ms 展示。期间用户开始输入 = 取消且不计已问。
 * 时钟/存储全部注入。
 */
export class AutoPromptPolicy {
  private candidate: Candidate | null = null
  private pendingShow: { runId: string; sessionId: string; reasons: string[]; at: number } | null =
    null
  private previousNegativeFollowup = new Map<string, boolean>()
  private askedRuns: string[]
  private askedSet: Set<string>
  private state: StoredState

  constructor(
    private now: () => number,
    askedRuns: string[] = [],
    state: Partial<StoredState> = {},
    private gates: () => GateContext = () => ({
      enabled: true,
      visible: true,
      composerEmpty: true,
      composerFocusedWithinMs: null,
      modalOpen: false,
    }),
  ) {
    this.askedRuns = [...askedRuns].slice(-ASKED_RUN_CAP)
    this.askedSet = new Set(this.askedRuns)
    this.state = {
      lastShownAt: state.lastShownAt ?? null,
      dismissStreak: state.dismissStreak ?? 0,
      cooldownUntil: state.cooldownUntil ?? 0,
      sessionDaily: state.sessionDaily ?? {},
    }
  }

  get askedRunIds(): string[] {
    return this.askedRuns
  }

  get persisted(): StoredState {
    return this.state
  }

  /** run 进入终态（或事件回放补齐）时被调用。live=false 的历史 run 直接忽略。 */
  runTerminal(signal: RunTerminalSignal, terminalAt: number): PromptEvent {
    // 新 run 终态替换旧候选 —— 先提交旧候选的 negative 轨迹，再丢弃。
    if (this.candidate) this.finishCandidate(this.candidate)
    this.pendingShow = null
    if (!signal.live || this.askedSet.has(signal.runId)) return { kind: "none" }
    const candidate: Candidate = {
      signal,
      terminalAt,
      best: { score: 0, reasons: [], negativeFollowup: false },
      previousNegative:
        this.previousNegativeFollowup.get(signal.sessionId) === true,
      negativeFollowup: false,
      followup: null,
    }
    this.candidate = candidate
    return this.reevaluate(candidate, null)
  }

  /** 用户在候选窗内发出了下一条消息 —— 只认“下一条”（第一条），
   *  补充后续信号并重评。``elapsed < 0`` 一律忽略 —— 说明上报的是
   *  候选终态之前的旧消息（如「加载更早」分页进来的历史 run），
   *  不是后续消息。 */
  followupSent(text: string, sentAt: number): PromptEvent {
    const candidate = this.candidate
    if (!candidate) return { kind: "none" }
    const elapsed = sentAt - candidate.terminalAt
    if (candidate.followup === null && elapsed >= 0 && elapsed <= FOLLOWUP_WINDOW_MS) {
      candidate.followup = { text, elapsedMs: elapsed }
    }
    return this.reevaluate(candidate, null)
  }

  /** 180s 窗到期 / 定期 tick / 延迟展示的结算点。 */
  tick(): PromptEvent {
    const pending = this.pendingShow
    if (pending && this.now() >= pending.at) {
      this.pendingShow = null
      return this.finishShow(pending)
    }
    const candidate = this.candidate
    if (candidate && this.now() - candidate.terminalAt > FOLLOWUP_WINDOW_MS) {
      this.finishCandidate(candidate)
    }
    return { kind: "none" }
  }

  /** 延迟窗口内用户开始输入 → 取消，且该 run 不标记为已问（G9）。 */
  composerActivity(): PromptEvent {
    if (this.pendingShow) {
      const runId = this.pendingShow.runId
      this.pendingShow = null
      return { kind: "cancelled", runId }
    }
    return { kind: "none" }
  }

  /** 用户点「不需要」。连续 2 次 → 24h 冷却。 */
  dismissed(runId: string): void {
    this.state.dismissStreak += 1
    if (this.state.dismissStreak >= DISMISS_STREAK_LIMIT) {
      this.state.cooldownUntil = this.now() + DISMISS_COOLDOWN_MS
      this.state.dismissStreak = 0
    }
    if (this.candidate) this.finishCandidate(this.candidate)
    this.pendingShow = null
    void runId
  }

  /** 用户点了「反馈」或完成提交 —— 重置连续拒绝计数。 */
  responded(): void {
    this.state.dismissStreak = 0
    if (this.candidate) this.finishCandidate(this.candidate)
    this.pendingShow = null
  }

  /** 20s 无操作自动收起 —— 不计 dismiss、不计 responded。 */
  ignored(): void {
    if (this.candidate) this.finishCandidate(this.candidate)
    this.pendingShow = null
  }

  private reevaluate(candidate: Candidate, _unused: null): PromptEvent {
    const score = scoreTerminalRun(
      candidate.signal,
      candidate.followup,
      candidate.previousNegative,
    )
    candidate.best = score
    if (score.negativeFollowup) candidate.negativeFollowup = true
    if (score.score < PROMPT_THRESHOLD) {
      // 分数不足但窗还没关 —— 保留候选，等待后续消息补足。
      if (this.now() - candidate.terminalAt > FOLLOWUP_WINDOW_MS) {
        this.finishCandidate(candidate)
      }
      return { kind: "none" }
    }
    if (this.pendingShow) return { kind: "none" }
    if (!this.gatesPass(this.gates(), candidate.signal.sessionId)) {
      // 门不满足 —— 不调度展示，也不算问过；候选保留到期。
      return { kind: "none" }
    }
    const delayUntil = Math.max(
      candidate.terminalAt + PROMPT_DELAY_MS,
      this.now() + PROMPT_DELAY_MS,
    )
    this.pendingShow = {
      runId: candidate.signal.runId,
      sessionId: candidate.signal.sessionId,
      reasons: score.reasons,
      at: delayUntil,
    }
    return {
      kind: "scheduled",
      runId: candidate.signal.runId,
      sessionId: candidate.signal.sessionId,
      reasons: score.reasons,
      delayMs: Math.max(0, delayUntil - this.now()),
    }
  }

  /** 展示时刻再查一次门 —— 1500ms 内状态可能已变；不满足则静默放弃。 */
  private finishShow(pending: {
    runId: string
    sessionId: string
    reasons: string[]
  }): PromptEvent {
    if (!this.gatesPass(this.gates(), pending.sessionId)) {
      return { kind: "none" }
    }
    this.markAsked(pending.runId, pending.sessionId)
    return {
      kind: "show",
      runId: pending.runId,
      sessionId: pending.sessionId,
      reasons: pending.reasons,
    }
  }

  /** 门的静态部分（调度 + 展示两次检查）：开关、可见性、输入框、
   *  Modal、冷却、重显示间隔、同会话当日上限。 */
  gatesPass(ctx: GateContext, sessionId: string): boolean {
    if (!ctx.enabled || !ctx.visible) return false
    if (!ctx.composerEmpty) return false
    if (ctx.composerFocusedWithinMs !== null && ctx.composerFocusedWithinMs < 3_000) {
      return false
    }
    if (ctx.modalOpen) return false
    const now = this.now()
    if (now < this.state.cooldownUntil) return false
    if (
      this.state.lastShownAt !== null &&
      now - this.state.lastShownAt < RESHOW_INTERVAL_MS
    ) {
      return false
    }
    if (this.sessionDailyCount(sessionId) >= SESSION_DAILY_LIMIT) return false
    return true
  }

  private markAsked(runId: string, sessionId: string): void {
    const now = this.now()
    this.state.lastShownAt = now
    const day = dayKey(now)
    // 每个会话各自记当天次数；只裁掉非当天的条目，其他会话当天计数保留。
    const daily = { ...(this.state.sessionDaily[sessionId] ?? {}) }
    daily[day] = (daily[day] ?? 0) + 1
    const nextDaily: Record<string, Record<string, number>> = {}
    for (const [sid, days] of Object.entries(this.state.sessionDaily)) {
      const today = Object.fromEntries(
        Object.entries(days).filter(([d]) => d === day),
      )
      if (Object.keys(today).length > 0) nextDaily[sid] = today
    }
    nextDaily[sessionId] = daily
    this.state.sessionDaily = nextDaily
    this.askedRuns.push(runId)
    if (this.askedRuns.length > ASKED_RUN_CAP) {
      this.askedRuns = this.askedRuns.slice(-ASKED_RUN_CAP)
    }
    this.askedSet = new Set(this.askedRuns)
    if (this.candidate) this.finishCandidate(this.candidate)
  }

  /** 候选结束：提交其 negative_followup 轨迹（true/false 都写——
   *  「上一 run 有没有抱怨」是完整记录，不是累积标记）。 */
  private finishCandidate(candidate: Candidate): void {
    if (this.candidate === candidate) this.candidate = null
    this.previousNegativeFollowup.set(
      candidate.signal.sessionId,
      candidate.negativeFollowup,
    )
  }

  /** 同会话当天已展示次数（G4 用）。 */
  sessionDailyCount(sessionId: string): number {
    return this.state.sessionDaily[sessionId]?.[dayKey(this.now())] ?? 0
  }

  canAskSession(sessionId: string): boolean {
    return this.sessionDailyCount(sessionId) < SESSION_DAILY_LIMIT
  }
}

// ---- 键值存储适配层（React hook 用） ------------------------------------

export function loadAskedRuns(storage: Pick<Storage, "getItem">): string[] {
  try {
    const raw = storage.getItem(STORAGE_ASKED)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list.filter((x) => typeof x === "string") : []
  } catch {
    return []
  }
}

export function loadPromptState(storage: Pick<Storage, "getItem">): Partial<StoredState> {
  try {
    const raw = storage.getItem(STORAGE_STATE)
    const parsed = raw ? JSON.parse(raw) : {}
    return typeof parsed === "object" && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

export function autoPromptEnabled(storage: Pick<Storage, "getItem">): boolean {
  return storage.getItem(STORAGE_KEY) !== "0"
}

// 持久化走第一方 cookie（同 rxy_theme 约定 —— 打包安全契约禁 web-storage）。
// 读 cookie 可能抛 SecurityError（禁用存储的浏览器/企业策略）：内存副本兜底，
// 功能仍可用，只是策略不跨会话持久化。
const _memoryStore = new Map<string, string>()

function _readCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  try {
    const match = document.cookie.match(
      new RegExp(
        "(?:^|;\\s*)" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)",
      ),
    )
    return match ? decodeURIComponent(match[1]) : null
  } catch {
    return null
  }
}

export type SafeStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">

export function safeStorage(): SafeStorage {
  return {
    getItem: (key: string) => {
      const value = _readCookie(key)
      if (value !== null) return value
      return _memoryStore.has(key) ? (_memoryStore.get(key) as string) : null
    },
    setItem: (key: string, value: string) => {
      _memoryStore.set(key, String(value))
      try {
        document.cookie = `${key}=${encodeURIComponent(String(value))};path=/;samesite=lax;max-age=31536000`
      } catch {
        // 内存副本仍在 —— 当次会话功能不受影响。
      }
    },
    removeItem: (key: string) => {
      _memoryStore.delete(key)
      try {
        document.cookie = `${key}=;path=/;samesite=lax;max-age=0`
      } catch {
        // 同上。
      }
    },
  }
}
