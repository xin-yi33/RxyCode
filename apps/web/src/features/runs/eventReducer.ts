// W9-F4: the §5.3/§5.4 event contract -> RunView projection, in the same
// reduce pass as the legacy W3/W6 Projection shape (tests drive those keys
// directly via bun). Every event type not in the contract table is ignored;
// input is deduped by seq and out-of-order events wait on the gap.
import { TERMINAL_RUN_STATUSES } from "./status"

export type RunEvent = {
  seq: number
  type: string
  payload: Record<string, unknown>
}

export type ToolStatus = "running" | "completed" | "failed"
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "cancelled"
export type QuestionOption = { label: string; value: string }
export type TaskEntry = { id: string; title: string; status: string }

export type TimelineItem =
  | { kind: "user"; seq: number; text: string }
  | { kind: "text"; seq: number; text: string }
  // 思考块：记录推理步数与思维链文本，前端折叠展示（默认收起，
  // 点击展开看原文）。文本本身已在事件流里——不再做隐藏假设。
  | { kind: "thinking"; seq: number; steps: number; text: string }
  | {
      kind: "tasks"
      seq: number
      items: TaskEntry[]
    }
  | {
      kind: "tool"
      seq: number
      callId: string
      tool: string
      title: string
      status: ToolStatus
      summary?: string
      // 展示用详情：参数（tool_begin 的 arguments）与结果文本，已截断。
      args?: string
      result?: string
      exitCode?: number
      durationMs?: number
    }
  | {
      kind: "approval"
      seq: number
      approvalId: string
      tool: string
      command: string
      description?: string
      workdir?: string
      status: ApprovalStatus
    }
  | {
      kind: "question"
      seq: number
      questionId: string
      header: string
      prompt: string
      options: QuestionOption[]
      // "choice" 只允许点选项；缺省/“text” 才显示自由输入框。
      inputType: "choice" | "text"
      answer?: string
      // question.resolved 到达即 true（即使 answer 为空串，卡片也必须折叠，
      // 不能因为 answer 是 falsy 又变回可交互）。
      answered?: boolean
    }
  | { kind: "final"; seq: number; text: string }

export type RunUsage = {
  tokens?: number
  amount?: string
  currency?: string
  modelId?: string
}

export type RunView = {
  runId: string
  status: string // 来自 run.status 事件；初始值来自 GET /runs/{id}
  activity: string // 最近一条 intermediate delta（"正在…"状态行）
  timeline: TimelineItem[] // 严格按 seq 排序，按 seq 去重
  usage: RunUsage // 未上报的字段保持 undefined，不写 0
  lastSeq: number
  leaseEpochs: number[] // worker.lease 事件的 epoch —— 控制台“续接次数”
}

// ---- 旧 W3/W6 投影契约（保留：tests 直接断言这些字段） ----------------------

export type ToolCard = {
  callId: string
  name: string
  status: "failed" | "completed"
}

export type ApprovalCard = {
  id: string
  status: string
}

export type PlanItem = { id: string; title: string; status: string }

export type AgentItem = {
  id: string
  name: string
  status: string
  cost: string
  parent_id?: string
  tokens?: number
}

export type QuestionItem = { id: string; prompt: string; answer: string }

export type Projection = {
  order: number[]
  answer: string
  intermediate: string[]
  tools: ToolCard[]
  approvals: ApprovalCard[]
  plans: PlanItem[]
  todos: PlanItem[]
  agents: AgentItem[]
  questions: QuestionItem[]
  runStatus: string
  // F4：同一趟归约产出的 §5.4 视图，Timeline/Console 消费它。
  view: RunView
}

// 旧事件名 → runStatus 的映射（W3 契约）；新契约只认 run.status 行。
const STATUS_BY_TYPE: Record<string, string> = {
  "run.queued": "queued",
  "run.started": "running",
  "run.completed": "succeeded",
  "run.failed": "failed",
  "run.cancelled": "cancelled",
  "run.recovery_required": "recovery_required",
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value)
}

// CLI 进度文案。它们会进 activity，不能写进「思考过程」。
function isStatusLine(text: string): boolean {
  return /^(Analyzing your request|Thinking\.\.\.|思考中|模型输出中|Generating\.\.\.)/i.test(
    text.trim(),
  )
}

function num(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}

// 与 OpenTUI streamReducer 相同的占位文案：liveness 心跳不是思维内容，
// 不进思考块（否则展开看到的是「思考中...」而不是推理）。
const THOUGHT_PLACEHOLDERS = new Set([
  "",
  "…",
  "...",
  "思考中...",
  "思考中…",
  "Done",
  "正在思考中...",
  "已思考完毕",
])

function isPlaceholderThought(text: string): boolean {
  return THOUGHT_PLACEHOLDERS.has(text.trim())
}

// 工具卡展开详情用：对象走 JSON 缩进，字符串原样，超限截断（不落库，仅展示）。
const DETAIL_CAP = 4000
// 思考块文本上限：推理可以很长，保留尾部而非撑爆 DOM。
const THINKING_CAP = 60000

function detail(value: unknown): string | undefined {
  if (value == null) return undefined
  let text = ""
  if (typeof value === "string") {
    text = value
  } else {
    try {
      text = JSON.stringify(value, null, 2)
    } catch {
      return undefined
    }
  }
  if (!text) return undefined
  return text.length > DETAIL_CAP ? `${text.slice(0, DETAIL_CAP)}…` : text
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

function approvalStatus(decision: string): ApprovalStatus {
  if (decision === "approved" || decision === "rejected") return decision
  if (decision === "expired" || decision === "cancelled") return decision
  // 未知决策同样结束 pending 态，折叠行按“已拒绝”显示。
  return "rejected"
}

function findTool(
  timeline: TimelineItem[],
  callId: string,
): Extract<TimelineItem, { kind: "tool" }> | undefined {
  for (const item of timeline) {
    if (item.kind === "tool" && item.callId === callId) return item
  }
  return undefined
}

function findApproval(
  timeline: TimelineItem[],
  approvalId: string,
): Extract<TimelineItem, { kind: "approval" }> | undefined {
  for (const item of timeline) {
    if (item.kind === "approval" && item.approvalId === approvalId) return item
  }
  return undefined
}

function findQuestion(
  timeline: TimelineItem[],
  questionId: string,
): Extract<TimelineItem, { kind: "question" }> | undefined {
  for (const item of timeline) {
    if (item.kind === "question" && item.questionId === questionId) return item
  }
  return undefined
}

function findTasks(
  timeline: TimelineItem[],
): Extract<TimelineItem, { kind: "tasks" }> | undefined {
  for (const item of timeline) {
    if (item.kind === "tasks") return item
  }
  return undefined
}

export function reduceEvents(
  events: RunEvent[],
  initialStatus = "",
  statusWatermark = 0,
  runId = "",
): Projection {
  const view: RunView = {
    runId,
    status: initialStatus,
    activity: "",
    timeline: [],
    usage: {},
    lastSeq: 0,
    leaseEpochs: [],
  }
  const projection: Projection = {
    order: [],
    answer: "",
    intermediate: [],
    tools: [],
    approvals: [],
    plans: [],
    todos: [],
    agents: [],
    questions: [],
    runStatus: initialStatus,
    view,
  }
  const leases = new Set<number>()
  let sealed = false // legacy answer：assistant.final 之后不再追加 delta

  // ---- §5.4 view 归约 -------------------------------------------------------

  const applyView = (event: RunEvent) => {
    const payload = event.payload ?? {}
    view.lastSeq = Math.max(view.lastSeq, event.seq)
    switch (event.type) {
      case "run.created": {
        view.timeline.push({
          kind: "user",
          seq: event.seq,
          text: str(payload.message),
        })
        return
      }
      case "run.status": {
        const status = str(payload.status)
        if (status) view.status = status
        return
      }
      case "worker.lease": {
        const epoch = num(payload.epoch)
        if (epoch !== undefined) leases.add(epoch)
        return
      }
      case "assistant.delta": {
        const text = str(payload.text)
        const channel = str(payload.channel)
        if (channel === "reasoning") {
          // 思维链累积进思考块（折叠展示）。语义与 OpenTUI streamReducer
          // 对齐：子代理 intermediate 丢弃；liveness 占位文案不是思维内容；
          // snapshot 是累计快照→替换而非追加；超长保留尾部。
          if (payload.intermediate === true) return
          if (isPlaceholderThought(text)) return
          const isSnapshot = payload.snapshot === true
          const capped =
            text.length > THINKING_CAP ? "…" + text.slice(-THINKING_CAP) : text
          const last = view.timeline[view.timeline.length - 1]
          if (last && last.kind === "thinking") {
            last.steps += 1
            last.text = isSnapshot ? capped : last.text + capped
            if (last.text.length > THINKING_CAP) {
              last.text = "…" + last.text.slice(-THINKING_CAP)
            }
          } else {
            view.timeline.push({
              kind: "thinking",
              seq: event.seq,
              steps: 1,
              text: capped,
            })
          }
          return
        }
        if (payload.intermediate === true) {
          // activity 只放行已知安全的 CLI 状态行；其它中间态文本可能
          // 含子代理原始输出，统一落到通用进度标签。
          view.activity = isStatusLine(text) ? text : "处理中…"
          return
        }
        const last = view.timeline[view.timeline.length - 1]
        if (last && last.kind === "text") {
          last.text += text
        } else {
          view.timeline.push({ kind: "text", seq: event.seq, text })
        }
        return
      }
      case "tool.started": {
        const callId = str(payload.call_id)
        const args = detail(payload.arguments)
        const found = findTool(view.timeline, callId)
        if (found) {
          found.tool = str(payload.tool) || found.tool
          found.title = str(payload.title) || found.title
          if (args !== undefined) found.args = args
        } else {
          view.timeline.push({
            kind: "tool",
            seq: event.seq,
            callId,
            tool: str(payload.tool),
            title: str(payload.title),
            status: "running",
            args,
          })
        }
        return
      }
      case "tool.completed":
      case "tool.failed": {
        const callId = str(payload.call_id)
        const status: ToolStatus = event.type === "tool.failed" ? "failed" : "completed"
        const summary = str(payload.summary)
        const result = detail(payload.result ?? payload.output)
        // exit_code/duration_ms 仅在协议带上时透传，绝不编造。
        const exitCode = num(payload.exit_code)
        const durationMs = num(payload.duration_ms)
        const found = findTool(view.timeline, callId)
        if (found) {
          found.status = status
          found.tool = str(payload.tool) || found.tool
          if (summary) found.summary = summary
          if (result !== undefined) found.result = result
          if (exitCode !== undefined) found.exitCode = exitCode
          if (durationMs !== undefined) found.durationMs = durationMs
        } else {
          // 没有对应 started —— 以完成状态插入（旧 run 的日志没有 tool.started）。
          view.timeline.push({
            kind: "tool",
            seq: event.seq,
            callId,
            tool: str(payload.tool),
            title: "",
            status,
            summary: summary || undefined,
            result,
            exitCode,
            durationMs,
          })
        }
        return
      }
      case "notify.event/tool_begin": {
        // 审计行（drain journal）：投影的 tool.* 行之前的原始协议参数，
        // 用来补齐工具卡的 arguments —— 同一 call_id 合并，不产生重复卡。
        const params = record(payload.params) ?? payload
        const callId = str(params.call_id ?? params.callId)
        const toolName = str(params.tool_name ?? params.tool ?? params.name)
        const argsRecord = record(params.arguments)
        // 与 worker 投影一致的标题提取：description/command/path/filePath。
        let title = str(params.title)
        if (!title && argsRecord) {
          for (const key of ["description", "command", "path", "filePath"]) {
            const value = argsRecord[key]
            if (value) {
              title = str(value).slice(0, 300)
              break
            }
          }
        }
        const args = detail(params.arguments ?? params.args)
        if (!callId && !toolName && args === undefined) return
        const found = callId ? findTool(view.timeline, callId) : undefined
        if (found) {
          found.tool = toolName || found.tool
          if (title) found.title = title
          if (args !== undefined) found.args = args
        } else {
          view.timeline.push({
            kind: "tool",
            seq: event.seq,
            callId,
            tool: toolName,
            title,
            status: "running",
            args,
          })
        }
        return
      }
      case "notify.event/tool_end": {
        const params = record(payload.params) ?? payload
        const callId = str(params.call_id ?? params.callId)
        const toolName = str(params.tool_name ?? params.tool ?? params.name)
        const okRaw = params.ok
        const statusText = str(params.status).toLowerCase()
        // ok 布尔优先；否则 status 文案里的失败词兜底，其余按成功。
        const failed =
          okRaw === false ||
          (okRaw == null &&
            (statusText === "failed" ||
              statusText === "error" ||
              statusText === "cancelled"))
        const result = detail(
          params.summary ?? params.result ?? params.output ?? params.error,
        )
        if (!callId) return
        const found = findTool(view.timeline, callId)
        if (found) {
          found.status = failed ? "failed" : "completed"
          found.tool = toolName || found.tool
          if (result !== undefined) {
            found.result = result
            if (!found.summary) found.summary = result
          }
        } else {
          view.timeline.push({
            kind: "tool",
            seq: event.seq,
            callId,
            tool: toolName,
            title: "",
            status: failed ? "failed" : "completed",
            summary: result,
            result,
          })
        }
        return
      }
      case "approval.requested": {
        const approvalId = str(payload.approval_id)
        if (!approvalId) return
        const args =
          payload.arguments && typeof payload.arguments === "object"
            ? (payload.arguments as Record<string, unknown>)
            : {}
        const found = findApproval(view.timeline, approvalId)
        const command = str(payload.command) || str(args.command)
        const description = str(args.description) || undefined
        const workdir = str(payload.workdir) || undefined
        if (found) {
          found.tool = str(payload.tool) || found.tool
          found.command = command || found.command
          if (description) found.description = description
          if (workdir) found.workdir = workdir
          found.status = "pending"
        } else {
          view.timeline.push({
            kind: "approval",
            seq: event.seq,
            approvalId,
            tool: str(payload.tool),
            command,
            description,
            workdir,
            status: "pending",
          })
        }
        return
      }
      case "approval.resolved": {
        const approvalId = str(payload.approval_id)
        if (!approvalId) return
        const status = approvalStatus(str(payload.decision ?? payload.status))
        const found = findApproval(view.timeline, approvalId)
        if (found) {
          found.status = status
        } else {
          view.timeline.push({
            kind: "approval",
            seq: event.seq,
            approvalId,
            tool: "",
            command: "",
            status,
          })
        }
        return
      }
      case "approval.resumed": {
        // 续接意味着此前已批准；把仍在 pending 的卡收尾为已批准。
        const found = findApproval(view.timeline, str(payload.approval_id))
        if (found && found.status === "pending") found.status = "approved"
        return
      }
      case "question.requested": {
        const questionId = str(payload.question_id)
        if (!questionId) return
        const rawOptions = Array.isArray(payload.options) ? payload.options : []
        const options: QuestionOption[] = rawOptions
          .map((item) => {
            if (!item || typeof item !== "object") return null
            const record = item as Record<string, unknown>
            return { label: str(record.label), value: str(record.value ?? record.label) }
          })
          .filter((item): item is QuestionOption => item !== null)
        const prompt = str(payload.prompt ?? payload.question)
        const header = str(payload.header)
        // 协议字段：choice 有选项且服务端只接受选项值；text 是自由输入。
        const inputType: "choice" | "text" =
          payload.input_type === "text" ||
          (payload.input_type === undefined && options.length === 0)
            ? "text"
            : "choice"
        const found = findQuestion(view.timeline, questionId)
        if (found) {
          found.prompt = prompt || found.prompt
          found.header = header || found.header
          if (options.length) found.options = options
          found.inputType = inputType
        } else {
          view.timeline.push({
            kind: "question",
            seq: event.seq,
            questionId,
            header,
            prompt,
            options,
            inputType,
          })
        }
        return
      }
      case "question.resolved": {
        const found = findQuestion(view.timeline, str(payload.question_id))
        if (found) {
          found.answer = str(payload.answer)
          found.answered = true
        }
        return
      }
      case "plan.updated":
      case "todo.updated": {
        // 计划/待办行：按 id 合并进唯一的「任务」清单块 —— 模型的
        // todo 快照每次是全量，worker 已拆成逐项事件，这里按 id 覆盖
        // 即可保持块内永远是当前真实清单。
        const id = str(payload.plan_id ?? payload.todo_id)
        const title = str(payload.title)
        const status = str(payload.status)
        let tasks = findTasks(view.timeline)
        if (!tasks) {
          tasks = { kind: "tasks", seq: event.seq, items: [] }
          view.timeline.push(tasks)
        }
        const entry = tasks.items.find((it) => it.id === id)
        if (entry) {
          if (title) entry.title = title
          entry.status = status
        } else if (id) {
          tasks.items.push({ id, title, status })
        }
        return
      }
      case "turn.paused": {
        // 状态显示“等待你的操作”；run.status 仍是权威 —— 终态与
        // 取消中的 run 不被 turn.paused 标记回退。
        if (
          !TERMINAL_RUN_STATUSES.has(view.status) &&
          view.status !== "cancel_requested"
        ) {
          view.status = "waiting_approval"
        }
        return
      }
      case "assistant.final": {
        const text = str(payload.text)
        view.timeline.push({ kind: "final", seq: event.seq, text })
        // 删除最后一个与 Final 文本完全相同的 text 项（delta 流的回显）。
        for (let index = view.timeline.length - 1; index >= 0; index -= 1) {
          const item = view.timeline[index]
          if (item.kind === "text" && item.text === text) {
            view.timeline.splice(index, 1)
            break
          }
        }
        return
      }
      case "usage.updated": {
        const tokens = num(payload.tokens)
        const amount = payload.amount == null ? undefined : str(payload.amount)
        const currency = payload.currency == null ? undefined : str(payload.currency)
        const modelId = payload.model_id == null ? undefined : str(payload.model_id)
        if (tokens !== undefined) view.usage.tokens = tokens
        if (amount !== undefined) view.usage.amount = amount
        if (currency !== undefined) view.usage.currency = currency
        if (modelId !== undefined) view.usage.modelId = modelId
        return
      }
      default:
        // 其他类型（notify.*、plan.*、agent.* 等）不进时间线。
        return
    }
  }

  // ---- 旧投影字段（W3/W6 契约） ---------------------------------------------

  const applyLegacy = (event: RunEvent) => {
    projection.order.push(event.seq)
    const payload = event.payload ?? {}
    const historical = event.seq <= statusWatermark
    const mapped = STATUS_BY_TYPE[event.type]
    if (!historical && mapped) projection.runStatus = mapped
    if (!historical && event.type === "run.status") {
      projection.runStatus = str(payload.status) || projection.runStatus
    }
    switch (event.type) {
      case "assistant.final": {
        projection.answer = str(payload.text)
        sealed = true
        return
      }
      case "assistant.delta": {
        const text = str(payload.text)
        const channel = str(payload.channel)
        if (channel === "reasoning" || channel === "status") return
        if (payload.intermediate === true) projection.intermediate.push(text)
        else if (!sealed) projection.answer += text
        return
      }
      case "tool.failed":
      case "tool.completed": {
        projection.tools.push({
          callId: str(payload.call_id),
          name: str(payload.tool),
          status: event.type === "tool.failed" ? "failed" : "completed",
        })
        return
      }
      case "approval.requested": {
        projection.approvals.push({
          id: str(payload.approval_id),
          status: "pending",
        })
        return
      }
      case "approval.resolved": {
        const id = str(payload.approval_id)
        const status = str(payload.decision ?? payload.status)
        const found = projection.approvals.find((item) => item.id === id)
        if (found) found.status = status
        else projection.approvals.push({ id, status })
        return
      }
      case "plan.updated":
      case "todo.updated": {
        const bucket = event.type === "plan.updated" ? projection.plans : projection.todos
        const id = str(payload.plan_id ?? payload.todo_id)
        const next = {
          id,
          title: str(payload.title),
          status: str(payload.status),
        }
        const found = bucket.find((item) => item.id === id)
        if (found) {
          found.title = next.title
          found.status = next.status
        } else if (id) bucket.push(next)
        return
      }
      case "agent.started":
      case "agent.completed":
      case "event/agent_started":
      case "event/agent_done": {
        const id = str(payload.agent_id)
        const status =
          event.type === "agent.completed" || event.type === "event/agent_done"
            ? "completed"
            : "started"
        const cost = str(payload.cost)
        const parentId = str(payload.parent_id)
        const tokens = num(payload.tokens ?? payload.total_tokens) ?? 0
        const found = projection.agents.find((item) => item.id === id)
        if (found) {
          found.status = status
          if (cost) found.cost = cost
          if (parentId) found.parent_id = parentId
          if (tokens) found.tokens = tokens
        } else {
          projection.agents.push({
            id,
            name: str(payload.name),
            status,
            cost,
            parent_id: parentId,
            tokens,
          })
        }
        return
      }
      case "question.requested": {
        const id = str(payload.question_id)
        if (id && !projection.questions.some((item) => item.id === id)) {
          projection.questions.push({ id, prompt: str(payload.prompt), answer: "" })
        }
        return
      }
      case "question.resolved": {
        const id = str(payload.question_id)
        const found = projection.questions.find((item) => item.id === id)
        if (found) found.answer = str(payload.answer)
        return
      }
      default:
        return
    }
  }

  const apply = (event: RunEvent) => {
    applyView(event)
    applyLegacy(event)
  }

  // seq 去重 + 缺口等待：乱序到达的事件先挂起，缺的那个到了再按序应用。
  const seen = new Set<number>()
  const waiting = new Map<number, RunEvent>()
  let next = 1
  const flush = () => {
    while (waiting.has(next)) {
      const event = waiting.get(next)
      waiting.delete(next)
      if (event) apply(event)
      next += 1
    }
  }
  for (const event of events) {
    if (!Number.isInteger(event.seq) || event.seq < 1 || seen.has(event.seq)) continue
    seen.add(event.seq)
    if (event.seq > next) {
      waiting.set(event.seq, event)
      continue
    }
    apply(event)
    next += 1
    flush()
  }
  view.leaseEpochs = [...leases].sort((a, b) => a - b)
  return projection
}

// Q1 Playwright 注入测试钩子：只在开发构建挂载，返回 §5.4 RunView。
declare global {
  interface Window {
    __rxyReduce?: (
      events: RunEvent[],
      runId?: string,
      initialStatus?: string,
    ) => RunView
  }
}

if (import.meta.env.DEV && typeof window !== "undefined") {
  window.__rxyReduce = (events, runId = "", initialStatus = "") =>
    reduceEvents(events, initialStatus, 0, runId).view
}
