export type RunEvent = {
  seq: number
  type: string
  payload: Record<string, unknown>
}

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
}

const STATUS_BY_TYPE: Record<string, string> = {
  "run.queued": "queued",
  "run.started": "running",
  "run.completed": "succeeded",
  "run.failed": "failed",
  "run.cancelled": "cancelled",
  "run.recovery_required": "recovery_required",
}

function textOf(payload: Record<string, unknown>): string {
  return String(payload.text ?? "")
}

export function reduceEvents(
  events: RunEvent[],
  initialStatus = "",
  statusWatermark = 0,
): Projection {
  const seen = new Set<number>()
  const pending = new Map<number, RunEvent>()
  let next = 1
  let sealed = false
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
  }

  const apply = (event: RunEvent) => {
    projection.order.push(event.seq)
    const payload = event.payload ?? {}
    const historical = event.seq <= statusWatermark
    const mapped = STATUS_BY_TYPE[event.type]
    if (!historical && mapped) projection.runStatus = mapped
    if (!historical && event.type === "run.status") {
      projection.runStatus = String(payload.status ?? projection.runStatus)
    }
    if (event.type === "assistant.final") {
      projection.answer = textOf(payload)
      sealed = true
      return
    }
    if (event.type === "assistant.delta") {
      if (payload.intermediate === true) projection.intermediate.push(textOf(payload))
      else if (!sealed) projection.answer += textOf(payload)
      return
    }
    if (event.type === "tool.failed" || event.type === "tool.completed") {
      projection.tools.push({
        callId: String(payload.call_id ?? ""),
        name: String(payload.tool ?? ""),
        status: event.type === "tool.failed" ? "failed" : "completed",
      })
      return
    }
    if (event.type === "approval.requested") {
      projection.approvals.push({
        id: String(payload.approval_id ?? ""),
        status: "pending",
      })
      return
    }
    if (event.type === "plan.updated" || event.type === "todo.updated") {
      const bucket = event.type === "plan.updated" ? projection.plans : projection.todos
      const id = String(payload.plan_id ?? payload.todo_id ?? "")
      const next = {
        id,
        title: String(payload.title ?? ""),
        status: String(payload.status ?? ""),
      }
      const found = bucket.find((item) => item.id === id)
      if (found) {
        found.title = next.title
        found.status = next.status
      } else if (id) bucket.push(next)
      return
    }
    if (
      event.type === "agent.started" ||
      event.type === "agent.completed" ||
      event.type === "event/agent_started" ||
      event.type === "event/agent_done"
    ) {
      const id = String(payload.agent_id ?? "")
      const status =
        event.type === "agent.completed" || event.type === "event/agent_done"
          ? "completed"
          : "started"
      const cost = String(payload.cost ?? "")
      const parentId = String(payload.parent_id ?? "")
      const tokens = Number(payload.tokens ?? 0)
      const found = projection.agents.find((item) => item.id === id)
      if (found) {
        found.status = status
        if (cost) found.cost = cost
        if (parentId) found.parent_id = parentId
        if (tokens) found.tokens = tokens
      } else {
        projection.agents.push({
          id,
          name: String(payload.name ?? ""),
          status,
          cost,
          parent_id: parentId,
          tokens,
        })
      }
      return
    }
    if (event.type === "question.requested") {
      const id = String(payload.question_id ?? "")
      if (id && !projection.questions.some((item) => item.id === id)) {
        projection.questions.push({ id, prompt: String(payload.prompt ?? ""), answer: "" })
      }
      return
    }
    if (event.type === "question.resolved") {
      const id = String(payload.question_id ?? "")
      const found = projection.questions.find((item) => item.id === id)
      if (found) found.answer = String(payload.answer ?? "")
      return
    }
    if (event.type === "approval.resolved") {
      const id = String(payload.approval_id ?? "")
      const status = String(payload.decision ?? payload.status ?? "")
      const found = projection.approvals.find((item) => item.id === id)
      if (found) found.status = status
      else projection.approvals.push({ id, status })
    }
  }

  const flush = () => {
    while (pending.has(next)) {
      const event = pending.get(next)
      pending.delete(next)
      if (event) apply(event)
      next += 1
    }
  }

  for (const event of events) {
    if (!Number.isInteger(event.seq) || event.seq < 1 || seen.has(event.seq)) continue
    seen.add(event.seq)
    if (event.seq > next) {
      pending.set(event.seq, event)
      continue
    }
    apply(event)
    next += 1
    flush()
  }
  return projection
}
