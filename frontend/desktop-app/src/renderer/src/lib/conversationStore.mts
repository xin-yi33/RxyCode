/**
 * Pure conversation/session state for the Phase4-D2 main window.
 *
 * Kept framework-agnostic and dependency-free (runtime) so the reducer
 * logic is unit-testable with the Node built-in test runner and stays
 * isolated from React and Electron (DC2/DC3).
 */
import type {
  ApprovalRequest,
  ErrorNotification,
  FinalAnswer,
  JobStatusUpdate,
  MessageDelta,
  RunComplete,
  ToolBegin,
  ToolEnd
} from '@rxycode/protocol-client'

export type MessageRole = 'user' | 'assistant'
export type MessageStatus = 'streaming' | 'complete' | 'error'
export type ToolCallStatus = 'running' | 'ok' | 'error' | 'recovering'
export type RunState =
  | 'queued'
  | 'running'
  | 'approval'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out'

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  status?: MessageStatus
  runId?: string
}

export interface ToolCall {
  callId: string
  toolName: string
  arguments?: Record<string, unknown>
  status: ToolCallStatus
  summary?: string
}

export interface UsageSnapshot {
  inputTokens: number | null
  outputTokens: number | null
  cacheHitTokens: number | null
  cacheWriteTokens: number | null
  cacheHitRate: number | null
  reportingStatus: 'reported' | 'partial' | 'not_reported'
}

export type TimelineItem =
  | {
      kind: 'user_prompt'
      id: string
      text: string
    }
  | {
      kind: 'assistant_text'
      id: string
      text: string
      status: MessageStatus
      runId?: string
    }
  | (ToolCall & { kind: 'tool_activity'; id: string })
  | {
      kind: 'recovery'
      id: string
      recoveryId: string
      sourceCallId?: string
      recoveryKind: 'transport_retry' | 'model_recovery' | 'graph_replan'
      state: 'running' | 'recovered' | 'exhausted'
      attempts: number
      maxAttempts: number
      errorKind: string
      summary?: string
      details: string[]
    }
  | {
      kind: 'child_agent'
      id: string
      sessionId: string
      agentId: string
      title: string
      state: RunState
      text?: string
    }
  | {
      kind: 'approval'
      id: string
      requestId: string
      action: string
      status: ApprovalRequestStatus
    }
  | {
      kind: 'final_answer'
      id: string
      text: string
      runId: string
      status: 'succeeded' | 'failed' | 'cancelled' | 'timed_out'
    }
  | {
      kind: 'error'
      id: string
      text: string
    }

export interface ChildSessionView {
  sessionId: string
  parentSessionId: string | null
  agentId: string
  state: RunState
  usage?: UsageSnapshot
  events?: ChildActivityEvent[]
}

export interface ChildActivityEvent {
  eventName: string
  text?: string
  toolName?: string
  summary?: string
  error?: string
}

export interface StepSnapshot {
  index: number
  total: number
  text: string
}

export interface MentionDispatchState {
  agentIds: string[]
  terminalChildIds: string[]
  summaries: string[]
  failed: boolean
}

export interface SessionEntry {
  sessionId: string
  title: string
  workspaceRoot: string
  createdAt: number
  updatedAt: number
  modelId: string | null
  providerId: string | null
  trashedAt: number | null
}

export interface ConversationState {
  sessions: SessionEntry[]
  activeSessionId: string | null
  messagesBySession: Record<string, ChatMessage[]>
  toolsBySession: Record<string, ToolCall[]>
  timelineBySession: Record<string, TimelineItem[]>
  usageBySession: Record<string, UsageSnapshot>
  planBySession: Record<string, string[]>
  stepBySession: Record<string, StepSnapshot>
  progressBySession: Record<string, string>
  childSessionsByRoot: Record<string, ChildSessionView[]>
  seenChildEventIds: Record<string, true>
  childEventCursorByRoot: Record<string, number>
  childEventGapByRoot: Record<string, boolean>
  sessionEventCursorBySession: Record<string, number>
  sessionEventGapBySession: Record<string, boolean>
  childLastSeqBySession: Record<string, number>
  mentionDispatchBySession: Record<string, MentionDispatchState>
  runningBySession: Record<string, boolean>
  runStateBySession: Record<string, RunState>
  errorBySession: Record<string, string | null>
  approvals: ApprovalRequestItem[]
}

export type ApprovalRequestStatus = 'pending' | 'submitting' | 'error'

export interface ApprovalRequestItem {
  requestId: string
  sessionId: string
  riskLevel: string
  action: string
  details?: Record<string, unknown>
  status: ApprovalRequestStatus
  error?: string
}

export interface NewSessionInput {
  sessionId: string
  workspaceRoot: string
  title?: string
  createdAt?: number
  updatedAt?: number
  modelId?: string | null
  providerId?: string | null
  trashedAt?: number | null
}

export interface TaskSummaryInput {
  session_id: string
  title?: string
  workspace_root: string
  model_id?: string | null
  provider_id?: string | null
  status?: RunState
  created_at?: string
  updated_at?: string
  trashed_at?: string | null
}

export interface PromptResult {
  runId: string
  status: string
  text: string
}

export function createInitialState(): ConversationState {
  return {
    sessions: [],
    activeSessionId: null,
    messagesBySession: {},
    toolsBySession: {},
    timelineBySession: {},
    usageBySession: {},
    planBySession: {},
    stepBySession: {},
    progressBySession: {},
    childSessionsByRoot: {},
    seenChildEventIds: {},
    childEventCursorByRoot: {},
    childEventGapByRoot: {},
    sessionEventCursorBySession: {},
    sessionEventGapBySession: {},
    childLastSeqBySession: {},
    mentionDispatchBySession: {},
    runningBySession: {},
    runStateBySession: {},
    errorBySession: {},
    approvals: []
  }
}

export interface ParsedAgentMentions {
  agentIds: string[]
  prompt: string
}

/** Parse OpenCode-style leading mentions, including RxyCode's batch extension. */
export function parseLeadingAgentMentions(text: string): ParsedAgentMentions | null {
  let remaining = text.trim()
  const agentIds: string[] = []
  while (remaining.startsWith('@')) {
    const match = /^@([a-z0-9][a-z0-9_-]*)(?:\s+|$)/.exec(remaining)
    if (match === null) return null
    agentIds.push(match[1]!)
    remaining = remaining.slice(match[0].length).trimStart()
  }
  return agentIds.length === 0
    ? null
    : { agentIds: [...new Set(agentIds)], prompt: remaining.trim() }
}

function defaultTitle(sessionId: string): string {
  return `会话 ${sessionId.slice(0, 8)}`
}

function messagesFor(state: ConversationState, sessionId: string): ChatMessage[] {
  return state.messagesBySession[sessionId] ?? []
}

function toolsFor(state: ConversationState, sessionId: string): ToolCall[] {
  return state.toolsBySession[sessionId] ?? []
}

export function timelineFor(state: ConversationState, sessionId: string): TimelineItem[] {
  return state.timelineBySession[sessionId] ?? []
}

function withTimeline(
  state: ConversationState,
  sessionId: string,
  timeline: TimelineItem[]
): ConversationState {
  return {
    ...state,
    timelineBySession: { ...state.timelineBySession, [sessionId]: timeline }
  }
}

function nextTimelineId(state: ConversationState, sessionId: string): string {
  return `${sessionId}:timeline:${timelineFor(state, sessionId).length}`
}

function appendTimeline(
  state: ConversationState,
  sessionId: string,
  item: TimelineItem
): ConversationState {
  return withTimeline(state, sessionId, [...timelineFor(state, sessionId), item])
}

function nextMessageId(state: ConversationState, sessionId: string, role: MessageRole): string {
  return `${sessionId}:${role}:${messagesFor(state, sessionId).length}`
}

function withMessages(
  state: ConversationState,
  sessionId: string,
  messages: ChatMessage[]
): ConversationState {
  return {
    ...state,
    messagesBySession: { ...state.messagesBySession, [sessionId]: messages }
  }
}

export function addSession(state: ConversationState, input: NewSessionInput): ConversationState {
  if (state.sessions.some((session) => session.sessionId === input.sessionId)) {
    return state
  }
  const session: SessionEntry = {
    sessionId: input.sessionId,
    title: input.title ?? defaultTitle(input.sessionId),
    workspaceRoot: input.workspaceRoot,
    createdAt: input.createdAt ?? Date.now(),
    updatedAt: input.updatedAt ?? input.createdAt ?? Date.now(),
    modelId: input.modelId ?? null,
    providerId: input.providerId ?? null,
    trashedAt: input.trashedAt ?? null
  }
  return {
    ...state,
    sessions: [...state.sessions, session],
    activeSessionId: session.sessionId,
    messagesBySession: { ...state.messagesBySession, [session.sessionId]: [] },
    timelineBySession: { ...state.timelineBySession, [session.sessionId]: [] },
    usageBySession: { ...state.usageBySession, [session.sessionId]: {
      inputTokens: null,
      outputTokens: null,
      cacheHitTokens: null,
      cacheWriteTokens: null,
      cacheHitRate: null,
      reportingStatus: 'not_reported'
    } },
    runningBySession: { ...state.runningBySession, [session.sessionId]: false },
    runStateBySession: { ...state.runStateBySession, [session.sessionId]: 'succeeded' },
    errorBySession: { ...state.errorBySession, [session.sessionId]: null }
  }
}

export function selectSession(state: ConversationState, sessionId: string): ConversationState {
  if (!state.sessions.some((session) => session.sessionId === sessionId)) {
    return state
  }
  if (state.activeSessionId === sessionId) {
    return state
  }
  return { ...state, activeSessionId: sessionId }
}

export function addUserMessage(
  state: ConversationState,
  sessionId: string,
  text: string
): ConversationState {
  const messages = [
    ...messagesFor(state, sessionId),
    {
      id: nextMessageId(state, sessionId, 'user'),
      role: 'user' as const,
      text,
      status: 'complete' as const
    }
  ]
  const timelineState = appendTimeline(state, sessionId, {
    kind: 'user_prompt',
    id: nextTimelineId(state, sessionId),
    text
  })
  return {
    ...withTimeline(withMessages(timelineState, sessionId, messages), sessionId, [
      ...timelineFor(timelineState, sessionId)
    ]),
    errorBySession: { ...state.errorBySession, [sessionId]: null },
    sessions: state.sessions.map((session) =>
      session.sessionId === sessionId && session.title.startsWith('会话 ')
        ? { ...session, title: text.slice(0, 20) }
        : session
    )
  }
}

export function beginAssistantMessage(
  state: ConversationState,
  sessionId: string
): ConversationState {
  const messages = [
    ...messagesFor(state, sessionId),
    {
      id: nextMessageId(state, sessionId, 'assistant'),
      role: 'assistant' as const,
      text: '',
      status: 'streaming' as const
    }
  ]
  const timelineState = appendTimeline(state, sessionId, {
    kind: 'assistant_text',
    id: nextTimelineId(state, sessionId),
    text: '',
    status: 'streaming'
  })
  return {
    ...withTimeline(withMessages(timelineState, sessionId, messages), sessionId, [
      ...timelineFor(timelineState, sessionId)
    ]),
    runningBySession: { ...state.runningBySession, [sessionId]: true },
    runStateBySession: { ...state.runStateBySession, [sessionId]: 'running' },
    errorBySession: { ...state.errorBySession, [sessionId]: null }
  }
}

export function applyMessageDelta(
  state: ConversationState,
  sessionId: string,
  delta: MessageDelta
): ConversationState {
  const messages = messagesFor(state, sessionId)
  const last = messages.at(-1)
  let next: ChatMessage[]
  if (last !== undefined && last.role === 'assistant' && last.status === 'streaming') {
    next = [...messages.slice(0, -1), { ...last, text: last.text + delta.text }]
  } else {
    next = [
      ...messages,
      {
        id: nextMessageId(state, sessionId, 'assistant'),
        role: 'assistant',
        text: delta.text,
        status: 'streaming'
      }
    ]
  }
  const timeline = timelineFor(state, sessionId)
  const lastTimeline = timeline.at(-1)
  const nextTimeline: TimelineItem[] =
    lastTimeline?.kind === 'assistant_text' && lastTimeline.status === 'streaming'
      ? [...timeline.slice(0, -1), { ...lastTimeline, text: lastTimeline.text + delta.text }]
      : [
          ...timeline,
          {
            kind: 'assistant_text' as const,
            id: nextTimelineId(state, sessionId),
            text: delta.text,
            status: 'streaming' as const
          }
        ]
  return {
    ...withTimeline(withMessages(state, sessionId, next), sessionId, nextTimeline),
    runningBySession: { ...state.runningBySession, [sessionId]: true }
  }
}

function completeAssistant(
  state: ConversationState,
  sessionId: string,
  text: string,
  runId: string,
  resultStatus = 'succeeded'
): ConversationState {
  const runState = runStateFromJob(resultStatus)
  const succeeded = runState === 'succeeded'
  const messages = messagesFor(state, sessionId)
  const last = messages.at(-1)
  const complete: ChatMessage = {
    id: last?.id ?? nextMessageId(state, sessionId, 'assistant'),
    role: 'assistant',
    text,
    status: succeeded ? 'complete' : 'error',
    runId
  }
  const next =
    last !== undefined && last.role === 'assistant'
      ? [...messages.slice(0, -1), complete]
      : [...messages, complete]
  const timeline = timelineFor(state, sessionId)
  const lastTimeline = timeline.at(-1)
  const nextTimeline: TimelineItem[] =
    lastTimeline?.kind === 'assistant_text'
      ? [
          ...timeline.slice(0, -1),
          { ...lastTimeline, text, status: succeeded ? 'complete' : 'error', runId }
        ]
      : [
          ...timeline,
          {
            kind: 'assistant_text',
            id: nextTimelineId(state, sessionId),
            text,
            status: succeeded ? 'complete' : 'error',
            runId
          }
        ]
  const tools = toolsFor(state, sessionId).map((tool) => {
    if (tool.status !== 'running' && tool.status !== 'recovering') return tool
    return succeeded
      ? { ...tool, status: 'ok' as const, summary: 'completed with final answer' }
      : { ...tool, status: 'error' as const, summary: `run ${resultStatus}` }
  })
  const finalizedTimeline = nextTimeline.map((item) => {
    if (item.kind !== 'tool_activity' || (item.status !== 'running' && item.status !== 'recovering')) {
      return item
    }
    return succeeded
      ? { ...item, status: 'ok' as const, summary: 'completed with final answer' }
      : { ...item, status: 'error' as const, summary: `run ${resultStatus}` }
  })
  return {
    ...withTimeline(withMessages(state, sessionId, next), sessionId, finalizedTimeline),
    toolsBySession: { ...state.toolsBySession, [sessionId]: tools },
    runningBySession: { ...state.runningBySession, [sessionId]: false },
    runStateBySession: { ...state.runStateBySession, [sessionId]: runState },
    errorBySession: { ...state.errorBySession, [sessionId]: succeeded ? null : `run ${resultStatus}` }
  }
}

export function applyFinalAnswer(
  state: ConversationState,
  sessionId: string,
  final: FinalAnswer
): ConversationState {
  if (timelineFor(state, sessionId).some((item) => item.kind === 'final_answer' && item.runId === final.run_id)) {
    return applyTokenUsage(state, sessionId, final as unknown as Record<string, unknown>)
  }
  const completed = completeAssistant(state, sessionId, final.text, final.run_id)
  const withFinal = appendTimeline(completed, sessionId, {
    kind: 'final_answer',
    id: `${sessionId}:final:${final.run_id}`,
    text: final.text,
    runId: final.run_id,
    status: 'succeeded'
  })
  return applyTokenUsage(withFinal, sessionId, final as unknown as Record<string, unknown>)
}

function timeFromProtocol(value: string | undefined, fallback: number): number {
  if (value === undefined || value.trim() === '') return fallback
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function hydrateSessions(
  state: ConversationState,
  summaries: TaskSummaryInput[]
): ConversationState {
  let next = state
  for (const summary of summaries) {
    const current = next.sessions.find((session) => session.sessionId === summary.session_id)
    const now = Date.now()
    next = addSession(next, {
      sessionId: summary.session_id,
      workspaceRoot: summary.workspace_root,
      title: summary.title,
      createdAt: timeFromProtocol(summary.created_at, now),
      updatedAt: timeFromProtocol(summary.updated_at, now),
      modelId: summary.model_id ?? null,
      providerId: summary.provider_id ?? null,
      trashedAt: summary.trashed_at === null || summary.trashed_at === undefined
        ? null
        : timeFromProtocol(summary.trashed_at, now)
    })
    if (current !== undefined) {
      next = {
        ...next,
        sessions: next.sessions.map((session) =>
          session.sessionId === summary.session_id
            ? {
                ...session,
                title: summary.title ?? session.title,
                workspaceRoot: summary.workspace_root,
                updatedAt: timeFromProtocol(summary.updated_at, session.updatedAt),
                modelId: summary.model_id ?? session.modelId,
                providerId: summary.provider_id ?? session.providerId,
                trashedAt:
                  summary.trashed_at === undefined
                    ? session.trashedAt
                    : summary.trashed_at === null
                      ? null
                      : timeFromProtocol(summary.trashed_at, session.trashedAt ?? now)
              }
            : session
        )
      }
    }
    if (summary.status !== undefined) {
      const status = summary.status
      const staleRunning = status === 'running'
      const runState = staleRunning ? 'queued' : status
      next = {
        ...next,
        runStateBySession: { ...next.runStateBySession, [summary.session_id]: runState },
        runningBySession: {
          ...next.runningBySession,
          [summary.session_id]: !staleRunning && isActiveRunState(runState) && runState !== 'queued'
        }
      }
    }
  }
  if (next.activeSessionId !== null && next.sessions.some((s) => s.sessionId === next.activeSessionId && s.trashedAt !== null)) {
    const fallback = next.sessions.find((session) => session.trashedAt === null)
    next = { ...next, activeSessionId: fallback?.sessionId ?? null }
  }
  return next
}

export function renameSession(
  state: ConversationState,
  sessionId: string,
  title: string
): ConversationState {
  const clean = title.trim()
  if (clean === '') return state
  return {
    ...state,
    sessions: state.sessions.map((session) =>
      session.sessionId === sessionId ? { ...session, title: clean, updatedAt: Date.now() } : session
    )
  }
}

export function setSessionModel(
  state: ConversationState,
  sessionId: string,
  modelId: string,
  providerId: string | null = null
): ConversationState {
  return {
    ...state,
    sessions: state.sessions.map((session) =>
      session.sessionId === sessionId
        ? { ...session, modelId, providerId, updatedAt: Date.now() }
        : session
    )
  }
}

export function trashSession(state: ConversationState, sessionId: string): ConversationState {
  const nextSessions = state.sessions.map((session) =>
    session.sessionId === sessionId ? { ...session, trashedAt: Date.now(), updatedAt: Date.now() } : session
  )
  const nextActive = state.activeSessionId === sessionId
    ? nextSessions.find((session) => session.trashedAt === null)?.sessionId ?? null
    : state.activeSessionId
  return { ...state, sessions: nextSessions, activeSessionId: nextActive }
}

export function restoreSession(state: ConversationState, sessionId: string): ConversationState {
  return {
    ...state,
    sessions: state.sessions.map((session) =>
      session.sessionId === sessionId ? { ...session, trashedAt: null, updatedAt: Date.now() } : session
    )
  }
}

export function releaseStaleRun(state: ConversationState, sessionId: string): ConversationState {
  const { [sessionId]: _progress, ...progressBySession } = state.progressBySession
  return {
    ...state,
    runningBySession: { ...state.runningBySession, [sessionId]: false },
    runStateBySession: { ...state.runStateBySession, [sessionId]: 'queued' },
    errorBySession: { ...state.errorBySession, [sessionId]: null },
    progressBySession
  }
}

export function purgeSession(state: ConversationState, sessionId: string): ConversationState {
  const sessions = state.sessions.filter((session) => session.sessionId !== sessionId)
  const {
    [sessionId]: _messages,
    ...messagesBySession
  } = state.messagesBySession
  const {
    [sessionId]: _tools,
    ...toolsBySession
  } = state.toolsBySession
  const {
    [sessionId]: _timeline,
    ...timelineBySession
  } = state.timelineBySession
  const {
    [sessionId]: _usage,
    ...usageBySession
  } = state.usageBySession
  const {
    [sessionId]: _running,
    ...runningBySession
  } = state.runningBySession
  const {
    [sessionId]: _runState,
    ...runStateBySession
  } = state.runStateBySession
  const {
    [sessionId]: _error,
    ...errorBySession
  } = state.errorBySession
  const {
    [sessionId]: _plan,
    ...planBySession
  } = state.planBySession
  const {
    [sessionId]: _step,
    ...stepBySession
  } = state.stepBySession
  const {
    [sessionId]: _progress,
    ...progressBySession
  } = state.progressBySession
  const {
    [sessionId]: _children,
    ...childSessionsByRoot
  } = state.childSessionsByRoot
  const {
    [sessionId]: _childCursor,
    ...childEventCursorByRoot
  } = state.childEventCursorByRoot
  const {
    [sessionId]: _childGap,
    ...childEventGapByRoot
  } = state.childEventGapByRoot
  const {
    [sessionId]: _sessionCursor,
    ...sessionEventCursorBySession
  } = state.sessionEventCursorBySession
  const {
    [sessionId]: _sessionGap,
    ...sessionEventGapBySession
  } = state.sessionEventGapBySession
  const childLastSeqBySession = Object.fromEntries(
    Object.entries(state.childLastSeqBySession).filter(([key]) => !key.startsWith(`${sessionId}:`))
  )
  const {
    [sessionId]: _mention,
    ...mentionDispatchBySession
  } = state.mentionDispatchBySession
  const activeSessionId = state.activeSessionId === sessionId
    ? sessions.find((session) => session.trashedAt === null)?.sessionId ?? null
    : state.activeSessionId
  return {
    ...state,
    sessions,
    activeSessionId,
    messagesBySession,
    toolsBySession,
    timelineBySession,
    usageBySession,
    runningBySession,
    runStateBySession,
    errorBySession,
    planBySession,
    stepBySession,
    progressBySession,
    childSessionsByRoot,
    childEventCursorByRoot,
    childEventGapByRoot,
    sessionEventCursorBySession,
    sessionEventGapBySession,
    childLastSeqBySession,
    mentionDispatchBySession,
    approvals: state.approvals.filter((approval) => approval.sessionId !== sessionId)
  }
}

export function applyPromptResult(
  state: ConversationState,
  sessionId: string,
  result: PromptResult
): ConversationState {
  const alreadyStreamedFinal = timelineFor(state, sessionId).some(
    (item) => item.kind === 'final_answer' && item.runId === result.runId
  )
  if (alreadyStreamedFinal) {
    return removeApprovalRequestsForSession(
      applyTokenUsage(state, sessionId, result as unknown as Record<string, unknown>),
      sessionId
    )
  }
  const completed = completeAssistant(state, sessionId, result.text, result.runId, result.status)
  const runState = runStateFromJob(result.status)
  if ((runState === 'failed' || runState === 'cancelled' || runState === 'timed_out') && result.text.trim() === '') {
    return applyError(
      removeApprovalRequestsForSession(completed, sessionId),
      sessionId,
      `run ${result.status}`
    )
  }
  const withFinal = appendTimeline(completed, sessionId, {
    kind: 'final_answer',
    id: `${sessionId}:final:${result.runId}`,
    text: result.text,
    runId: result.runId,
    status: runState === 'failed' || runState === 'cancelled' || runState === 'timed_out'
      ? runState
      : 'succeeded'
  })
  return removeApprovalRequestsForSession(withFinal, sessionId)
}

export function applyError(
  state: ConversationState,
  sessionId: string,
  message: string
): ConversationState {
  const messages = messagesFor(state, sessionId)
  const last = messages.at(-1)
  const tools = toolsFor(state, sessionId).map((tool) =>
    tool.status === 'running' ? { ...tool, status: 'error' as const, summary: message } : tool
  )
  const initialTimeline = timelineFor(state, sessionId)
  const initialLast = initialTimeline.at(-1)
  const completedTimelineState =
    initialLast?.kind === 'assistant_text' && initialLast.status === 'streaming'
      ? withTimeline(state, sessionId, [
          ...initialTimeline.slice(0, -1),
          { ...initialLast, text: message, status: 'error' }
        ])
      : state
  const completedTimeline = timelineFor(completedTimelineState, sessionId)
  const completedLast = completedTimeline.at(-1)
  const withErrorTimeline =
    completedLast?.kind === 'error' && completedLast.text === message
      ? completedTimelineState
      : appendTimeline(completedTimelineState, sessionId, {
          kind: 'error',
          id: `${sessionId}:error:${completedTimeline.length}`,
          text: message
        })
  const finalizedErrorTimeline = withTimeline(
    withErrorTimeline,
    sessionId,
    timelineFor(withErrorTimeline, sessionId).map((item) =>
      item.kind === 'tool_activity' && item.status === 'running'
        ? { ...item, status: 'error' as const, summary: message }
        : item
    )
  )
  if (last !== undefined && last.role === 'assistant' && last.status === 'error') {
    return {
      ...finalizedErrorTimeline,
      toolsBySession: { ...state.toolsBySession, [sessionId]: tools },
      runningBySession: { ...state.runningBySession, [sessionId]: false },
      runStateBySession: { ...state.runStateBySession, [sessionId]: 'failed' },
      errorBySession: { ...state.errorBySession, [sessionId]: message }
    }
  }
  let next: ChatMessage[]
  if (last !== undefined && last.role === 'assistant' && last.status === 'streaming') {
    next = [...messages.slice(0, -1), { ...last, text: message, status: 'error' }]
  } else {
    next = [
      ...messages,
      {
        id: nextMessageId(state, sessionId, 'assistant'),
        role: 'assistant',
        text: message,
        status: 'error'
      }
    ]
  }
  return {
    ...withMessages(finalizedErrorTimeline, sessionId, next),
    toolsBySession: { ...state.toolsBySession, [sessionId]: tools },
    runningBySession: { ...state.runningBySession, [sessionId]: false },
    runStateBySession: { ...state.runStateBySession, [sessionId]: 'failed' },
    errorBySession: { ...state.errorBySession, [sessionId]: message }
  }
}

/**
 * Finish the renderer-side transport leg without presenting a recoverable
 * disconnect as the task's final answer. The server remains authoritative and
 * replaySessionEvents() may replace this local row with the real terminal
 * event immediately after reconnect.
 */
export function applyTransportRecovery(
  state: ConversationState,
  sessionId: string,
  message: string
): ConversationState {
  const recoveryId = `transport:${sessionId}:${timelineFor(state, sessionId).length}`
  let next = applyRecoveryEvent(state, 'event/recovery_started', {
    session_id: sessionId,
    recovery_id: recoveryId,
    recovery_kind: 'transport_retry',
    error_kind: 'transport',
    max_attempts: 1
  })
  next = applyRecoveryEvent(next, 'event/recovery_resolved', {
    session_id: sessionId,
    recovery_id: recoveryId,
    attempts: 1,
    display_summary: `已重新连接，任务状态正在恢复（${message}）`
  })
  return {
    ...next,
    runningBySession: { ...next.runningBySession, [sessionId]: false },
    runStateBySession: { ...next.runStateBySession, [sessionId]: 'queued' },
    errorBySession: { ...next.errorBySession, [sessionId]: null }
  }
}

export function setRunning(
  state: ConversationState,
  sessionId: string,
  running: boolean
): ConversationState {
  return {
    ...state,
    runningBySession: { ...state.runningBySession, [sessionId]: running },
    runStateBySession: {
      ...state.runStateBySession,
      [sessionId]: running ? 'running' : 'succeeded'
    }
  }
}

export function beginMentionDispatch(
  state: ConversationState,
  sessionId: string,
  agentIds: string[]
): ConversationState {
  return {
    ...state,
    mentionDispatchBySession: {
      ...state.mentionDispatchBySession,
      [sessionId]: { agentIds, terminalChildIds: [], summaries: [], failed: false }
    },
    runningBySession: { ...state.runningBySession, [sessionId]: true },
    runStateBySession: { ...state.runStateBySession, [sessionId]: 'running' }
  }
}

function runStateFromJob(value: unknown): RunState {
  switch (value) {
    case 'queued':
    case 'submitted':
      return 'queued'
    case 'running':
      return 'running'
    case 'approval':
      return 'approval'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    case 'timed_out':
      return 'timed_out'
    default:
      return 'succeeded'
  }
}

function isActiveRunState(value: RunState): boolean {
  return value === 'queued' || value === 'running' || value === 'approval'
}

export function applyToolBegin(
  state: ConversationState,
  sessionId: string,
  tool: ToolBegin
): ConversationState {
  const tools = toolsFor(state, sessionId)
  const card: ToolCall = {
    callId: tool.call_id,
    toolName: tool.tool_name,
    arguments: tool.arguments,
    status: 'running'
  }
  const existing = tools.findIndex((entry) => entry.callId === tool.call_id)
  const next =
    existing >= 0
      ? [...tools.slice(0, existing), card, ...tools.slice(existing + 1)]
      : [...tools, card]
  const timeline = timelineFor(state, sessionId)
  const timelineIndex = timeline.findIndex(
    (item) => item.kind === 'tool_activity' && item.callId === tool.call_id
  )
  const timelineCard: TimelineItem = {
    kind: 'tool_activity',
    id: `${sessionId}:tool:${tool.call_id}`,
    callId: tool.call_id,
    toolName: tool.tool_name,
    arguments: tool.arguments,
    status: 'running'
  }
  const nextTimeline =
    timelineIndex >= 0
      ? [...timeline.slice(0, timelineIndex), timelineCard, ...timeline.slice(timelineIndex + 1)]
      : [...timeline, timelineCard]
  return {
    ...withTimeline(state, sessionId, nextTimeline),
    toolsBySession: { ...state.toolsBySession, [sessionId]: next }
  }
}

export function applyToolEnd(
  state: ConversationState,
  sessionId: string,
  tool: ToolEnd
): ConversationState {
  const tools = toolsFor(state, sessionId)
  const index = tools.findIndex((entry) => entry.callId === tool.call_id)
  if (index < 0) return state
  const next = [...tools]
  next[index] = {
    ...tools[index]!,
    status: tool.ok ? 'ok' : 'error',
    summary: tool.summary
  }
  const timeline = timelineFor(state, sessionId)
  const timelineIndex = timeline.findIndex(
    (item) => item.kind === 'tool_activity' && item.callId === tool.call_id
  )
  const nextTimeline: TimelineItem[] =
    timelineIndex < 0
      ? timeline
      : [
          ...timeline.slice(0, timelineIndex),
          {
            ...timeline[timelineIndex]!,
            status: tool.ok ? 'ok' : 'error',
            summary: tool.summary
          } as TimelineItem,
          ...timeline.slice(timelineIndex + 1)
        ]
  return {
    ...withTimeline(state, sessionId, nextTimeline),
    toolsBySession: { ...state.toolsBySession, [sessionId]: next }
  }
}

export function applyRunComplete(
  state: ConversationState,
  sessionId: string,
  done: RunComplete
): ConversationState {
  const messages = messagesFor(state, sessionId)
  const last = messages.at(-1)
  let next = messages
  if (last !== undefined && last.role === 'assistant' && last.status === 'streaming') {
    const failed = done.status === 'failed' || done.status === 'timed_out' || done.status === 'cancelled'
    next = [
      ...messages.slice(0, -1),
      {
        ...last,
        status: failed ? ('error' as const) : ('complete' as const),
        runId: done.run_id
      }
    ]
  }
  const tools = toolsFor(state, sessionId).map((tool) =>
    tool.status === 'running' ? { ...tool, status: 'error' as const, summary: 'interrupted' } : tool
  )
  const timeline = timelineFor(state, sessionId).map((item) =>
    item.kind === 'tool_activity' && item.status === 'running'
      ? { ...item, status: 'error' as const, summary: 'interrupted' }
      : item
  )
  const failed = done.status === 'failed' || done.status === 'timed_out' || done.status === 'cancelled'
  const runState = runStateFromJob(done.status)
  return {
    ...state,
    messagesBySession: { ...state.messagesBySession, [sessionId]: next },
    toolsBySession: { ...state.toolsBySession, [sessionId]: tools },
    timelineBySession: { ...state.timelineBySession, [sessionId]: timeline },
    runningBySession: { ...state.runningBySession, [sessionId]: false },
    runStateBySession: { ...state.runStateBySession, [sessionId]: runState },
    errorBySession: {
      ...state.errorBySession,
      [sessionId]: failed ? `run ${done.status}` : null
    },
    approvals: state.approvals.filter((approval) => approval.sessionId !== sessionId)
  }
}

function tokenOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function reportingStatusOf(value: unknown): UsageSnapshot['reportingStatus'] {
  return value === 'reported' || value === 'partial' ? value : 'not_reported'
}

export function applyTokenUsage(
  state: ConversationState,
  sessionId: string,
  usage: Record<string, unknown>
): ConversationState {
  return {
    ...state,
    usageBySession: {
      ...state.usageBySession,
      [sessionId]: {
        inputTokens: tokenOrNull(usage.input_tokens),
        outputTokens: tokenOrNull(usage.output_tokens),
        cacheHitTokens: tokenOrNull(usage.cache_hit_tokens),
        cacheWriteTokens: tokenOrNull(usage.cache_write_tokens),
        cacheHitRate: tokenOrNull(usage.cache_hit_rate),
        reportingStatus: reportingStatusOf(usage.reporting_status)
      }
    }
  }
}

function recoveryKindOf(value: unknown): 'transport_retry' | 'model_recovery' | 'graph_replan' {
  return value === 'transport_retry' || value === 'graph_replan' ? value : 'model_recovery'
}

export function applyRecoveryEvent(
  state: ConversationState,
  method: string,
  raw: Record<string, unknown>
): ConversationState {
  const sessionId = typeof raw.session_id === 'string' ? raw.session_id : ''
  const recoveryId = typeof raw.recovery_id === 'string' ? raw.recovery_id : ''
  if (sessionId === '' || recoveryId === '') return state
  const timeline = timelineFor(state, sessionId)
  const index = timeline.findIndex(
    (item) => item.kind === 'recovery' && item.recoveryId === recoveryId
  )
  const existing = index >= 0 && timeline[index]?.kind === 'recovery' ? timeline[index] : undefined
  const terminalRecovery = existing?.state === 'recovered' || existing?.state === 'exhausted'
  // Replayed notifications can arrive out of order after reconnect. A stale
  // started/analyzing/attempt event must never reopen a terminal recovery or
  // return its source tool to a spinner.
  if (terminalRecovery && method !== 'event/recovery_resolved' && method !== 'event/recovery_exhausted') {
    return state
  }
  if (existing?.state === 'exhausted' && method === 'event/recovery_resolved') return state
  if (existing?.state === 'recovered' && method === 'event/recovery_exhausted') return state
  const nextItem: TimelineItem =
    method === 'event/recovery_started'
      ? {
          kind: 'recovery',
          id: `${sessionId}:recovery:${recoveryId}`,
          recoveryId,
          sourceCallId: typeof raw.source_call_id === 'string' ? raw.source_call_id : undefined,
          recoveryKind: recoveryKindOf(raw.recovery_kind),
          state: 'running',
          attempts: 0,
          maxAttempts: typeof raw.max_attempts === 'number' ? raw.max_attempts : 3,
          errorKind: typeof raw.error_kind === 'string' ? raw.error_kind : 'tool_error',
          details: []
        }
      : {
          ...(existing ?? {
            kind: 'recovery' as const,
            id: `${sessionId}:recovery:${recoveryId}`,
            recoveryId,
            sourceCallId: typeof raw.source_call_id === 'string' ? raw.source_call_id : undefined,
            recoveryKind: recoveryKindOf(raw.recovery_kind),
            state: 'running' as const,
            attempts: 0,
            maxAttempts: 3,
            errorKind: 'tool_error',
            details: []
          }),
          ...(method === 'event/recovery_resolved'
            ? {
                state: 'recovered' as const,
                attempts: typeof raw.attempts === 'number' ? raw.attempts : existing?.attempts ?? 0,
                summary: typeof raw.display_summary === 'string' ? raw.display_summary : '已自动恢复'
              }
            : {}),
          ...(method === 'event/recovery_exhausted'
            ? {
                state: 'exhausted' as const,
                attempts: typeof raw.attempts === 'number' ? raw.attempts : existing?.attempts ?? 0,
                summary: typeof raw.final_error === 'string' ? raw.final_error : '自动恢复失败'
              }
            : {}),
          ...(method === 'event/recovery_attempt'
            ? {
                state: 'running' as const,
                attempts: typeof raw.attempt === 'number' ? raw.attempt : existing?.attempts ?? 0,
                details:
                  typeof raw.display_summary === 'string'
                    ? [...(existing?.details ?? []), raw.display_summary]
                    : existing?.details ?? []
              }
            : {}),
          ...(method === 'event/recovery_analyzing'
            ? {
                details: [...(existing?.details ?? []), '正在分析恢复路径']
              }
            : {})
        }
  const nextTimeline =
    index >= 0
      ? [...timeline.slice(0, index), nextItem, ...timeline.slice(index + 1)]
      : [...timeline, nextItem]
  let nextState = withTimeline(state, sessionId, nextTimeline)
  if (method === 'event/recovery_started') {
    const sourceCallId = typeof raw.source_call_id === 'string' ? raw.source_call_id : ''
    if (sourceCallId !== '') {
      const activeTimeline = timelineFor(nextState, sessionId)
      nextState = withTimeline(
        nextState,
        sessionId,
        activeTimeline.map((item) =>
          item.kind === 'tool_activity' && item.callId === sourceCallId
            ? { ...item, status: 'recovering' as const }
            : item
        )
      )
    }
  }
  if (method === 'event/recovery_resolved' && existing?.sourceCallId !== undefined) {
    const activeTimeline = timelineFor(nextState, sessionId)
    nextState = withTimeline(
      nextState,
      sessionId,
      activeTimeline.map((item) =>
        item.kind === 'tool_activity' && item.callId === existing.sourceCallId
          ? { ...item, status: 'ok' as const, summary: 'recovered automatically' }
          : item
      )
    )
  }
  if (method === 'event/recovery_exhausted' && existing?.sourceCallId !== undefined) {
    const activeTimeline = timelineFor(nextState, sessionId)
    nextState = withTimeline(
      nextState,
      sessionId,
      activeTimeline.map((item) =>
        item.kind === 'tool_activity' && item.callId === existing.sourceCallId
          ? { ...item, status: 'error' as const }
          : item
      )
    )
  }
  return nextState
}

function childRunState(method: string, payload: Record<string, unknown>): RunState {
  switch (method.slice('child_session/'.length)) {
    case 'created':
    case 'queued':
    case 'context_ready':
      return 'queued'
    case 'started':
    case 'tool_call':
    case 'progress':
    case 'partial_result':
      return 'running'
    case 'approval_required':
      return 'approval'
    case 'failed':
    case 'denied':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    case 'timed_out':
      return 'timed_out'
    case 'recovered':
      return typeof payload.status === 'string' ? runStateFromJob(payload.status) : 'running'
    default:
      return 'succeeded'
  }
}

export function applyChildSessionEvent(
  state: ConversationState,
  method: string,
  rawEvent: Record<string, unknown>
): ConversationState {
  const eventId = typeof rawEvent.event_id === 'string' ? rawEvent.event_id : null
  if (eventId !== null && state.seenChildEventIds[eventId] === true) return state
  const rootSessionId =
    typeof rawEvent.root_session_id === 'string'
      ? rawEvent.root_session_id
      : typeof rawEvent.parent_session_id === 'string'
        ? rawEvent.parent_session_id
        : null
  const sessionId = typeof rawEvent.session_id === 'string' ? rawEvent.session_id : null
  if (rootSessionId === null || sessionId === null) return state
  const eventSeq =
    typeof rawEvent.seq === 'number' && Number.isInteger(rawEvent.seq) && rawEvent.seq >= 0
      ? rawEvent.seq
      : null
  const seqKey = `${rootSessionId}:${sessionId}`
  const previousSeq = state.childLastSeqBySession[seqKey]
  if (
    eventSeq !== null &&
    previousSeq !== undefined && eventSeq <= previousSeq
  ) {
    return eventId === null
      ? state
      : { ...state, seenChildEventIds: { ...state.seenChildEventIds, [eventId]: true } }
  }
  const parentSessionId =
    typeof rawEvent.parent_session_id === 'string' ? rawEvent.parent_session_id : null
  const payload =
    typeof rawEvent.payload === 'object' && rawEvent.payload !== null
      ? (rawEvent.payload as Record<string, unknown>)
      : {}
  const children = state.childSessionsByRoot[rootSessionId] ?? []
  const index = children.findIndex((entry) => entry.sessionId === sessionId)
  const existing = index >= 0 ? children[index] : undefined
  const agentId =
    typeof payload.agent_id === 'string'
      ? payload.agent_id
      : typeof rawEvent.agent_id === 'string'
        ? rawEvent.agent_id
        : existing?.agentId ?? 'child'
  const rawUsage =
    typeof payload.usage === 'object' && payload.usage !== null
      ? (payload.usage as Record<string, unknown>)
      : null
  const childUsage = rawUsage === null
    ? existing?.usage
    : {
        inputTokens: tokenOrNull(rawUsage.input_tokens),
        outputTokens: tokenOrNull(rawUsage.output_tokens),
        cacheHitTokens: tokenOrNull(rawUsage.cache_hit_tokens),
        cacheWriteTokens: tokenOrNull(rawUsage.cache_write_tokens),
        cacheHitRate: tokenOrNull(rawUsage.cache_hit_rate),
        reportingStatus: reportingStatusOf(rawUsage.reporting_status)
      }
  const eventName = method.slice('child_session/'.length)
  const childError = typeof payload.error === 'string'
    ? payload.error
    : typeof payload.error === 'object' && payload.error !== null && typeof (payload.error as Record<string, unknown>).message === 'string'
      ? String((payload.error as Record<string, unknown>).message)
      : undefined
  const childActivity: ChildActivityEvent = {
    eventName,
    ...(typeof payload.text === 'string' ? { text: payload.text } : {}),
    ...(typeof payload.tool_name === 'string' ? { toolName: payload.tool_name } : {}),
    ...(typeof payload.summary === 'string' ? { summary: payload.summary } : {}),
    ...(childError === undefined ? {} : { error: childError })
  }
  const hasChildActivity = childActivity.text !== undefined || childActivity.toolName !== undefined ||
    childActivity.summary !== undefined || childActivity.error !== undefined
  const nextChildEvents = hasChildActivity
    ? [...(existing?.events ?? []), childActivity]
    : existing?.events
  const nextChild: ChildSessionView = {
    sessionId,
    parentSessionId,
    agentId,
    state: childRunState(method, payload),
    ...(childUsage === undefined ? {} : { usage: childUsage }),
    ...(nextChildEvents === undefined ? {} : { events: nextChildEvents })
  }
  const nextChildren =
    index < 0
      ? [...children, nextChild]
      : [...children.slice(0, index), { ...children[index]!, ...nextChild }, ...children.slice(index + 1)]
  let nextState: ConversationState = {
    ...state,
    childSessionsByRoot: { ...state.childSessionsByRoot, [rootSessionId]: nextChildren },
    childEventCursorByRoot: eventSeq === null
      ? state.childEventCursorByRoot
      : {
          ...state.childEventCursorByRoot,
          [rootSessionId]: Math.max(state.childEventCursorByRoot[rootSessionId] ?? 0, eventSeq)
        },
    childEventGapByRoot: eventSeq === null
      ? state.childEventGapByRoot
      : {
          ...state.childEventGapByRoot,
          [rootSessionId]:
            state.childEventGapByRoot[rootSessionId] === true ||
            eventSeq > (state.childEventCursorByRoot[rootSessionId] ?? 0) + 1
        },
    childLastSeqBySession: eventSeq === null
      ? state.childLastSeqBySession
      : { ...state.childLastSeqBySession, [seqKey]: eventSeq },
    seenChildEventIds:
      eventId === null ? state.seenChildEventIds : { ...state.seenChildEventIds, [eventId]: true }
  }
  const childTimeline = timelineFor(nextState, rootSessionId)
  const childTimelineIndex = childTimeline.findIndex(
    (item) => item.kind === 'child_agent' && item.sessionId === sessionId
  )
  const childItem: TimelineItem = {
    kind: 'child_agent',
    id: `${rootSessionId}:child:${sessionId}`,
    sessionId,
    agentId,
    title:
      typeof payload.title === 'string'
        ? payload.title
        : typeof payload.task_title === 'string'
          ? payload.task_title
          : `@${agentId}`,
    state: childRunState(method, payload),
    ...(typeof payload.text === 'string' ? { text: payload.text } : {})
  }
  const nextChildTimeline =
    childTimelineIndex >= 0
      ? [
          ...childTimeline.slice(0, childTimelineIndex),
          { ...childTimeline[childTimelineIndex], ...childItem } as TimelineItem,
          ...childTimeline.slice(childTimelineIndex + 1)
        ]
      : [...childTimeline, childItem]
  nextState = withTimeline(nextState, rootSessionId, nextChildTimeline)
  const terminalKind = eventName
  const isTerminal = ['completed', 'failed', 'cancelled', 'timed_out', 'denied'].includes(terminalKind)
  const dispatch = state.mentionDispatchBySession[rootSessionId]
  if (!isTerminal || dispatch === undefined || dispatch.terminalChildIds.includes(sessionId)) {
    return nextState
  }
  const error =
    typeof payload.error === 'object' && payload.error !== null
      ? (payload.error as Record<string, unknown>)
      : null
  const summary =
    typeof payload.summary === 'string' && payload.summary.trim() !== ''
      ? payload.summary.trim()
      : typeof error?.message === 'string'
        ? error.message
        : `Child finished with status ${terminalKind}`
  const updatedDispatch: MentionDispatchState = {
    ...dispatch,
    terminalChildIds: [...dispatch.terminalChildIds, sessionId],
    summaries: [...dispatch.summaries, `### @${agentId}\n\n${summary}`],
    failed: dispatch.failed || terminalKind !== 'completed'
  }
  nextState = {
    ...nextState,
    mentionDispatchBySession: {
      ...nextState.mentionDispatchBySession,
      [rootSessionId]: updatedDispatch
    }
  }
  if (updatedDispatch.terminalChildIds.length < dispatch.agentIds.length) return nextState
  const completed = completeAssistant(
    nextState,
    rootSessionId,
    updatedDispatch.summaries.join('\n\n'),
    `mention:${rootSessionId}`,
    updatedDispatch.failed ? 'failed' : 'succeeded'
  )
  const withFinalAnswer = appendTimeline(completed, rootSessionId, {
    kind: 'final_answer',
    id: `${rootSessionId}:final:mention`,
    text: updatedDispatch.summaries.join('\n\n'),
    runId: `mention:${rootSessionId}`,
    status: updatedDispatch.failed ? 'failed' : 'succeeded'
  })
  const remainingDispatches = { ...completed.mentionDispatchBySession }
  delete remainingDispatches[rootSessionId]
  return { ...withFinalAnswer, mentionDispatchBySession: remainingDispatches }
}

export function hydrateChildSessions(
  state: ConversationState,
  rootSessionId: string,
  rawSessions: Record<string, unknown>[],
  cursor: number
): ConversationState {
  const sessions: ChildSessionView[] = rawSessions.flatMap((raw) => {
    if (typeof raw.session_id !== 'string') return []
    return [{
      sessionId: raw.session_id,
      parentSessionId: typeof raw.parent_session_id === 'string' ? raw.parent_session_id : null,
      agentId: typeof raw.agent_id === 'string' ? raw.agent_id : 'child',
      state: runStateFromJob(raw.status)
    }]
  })
  return {
    ...state,
    childSessionsByRoot: { ...state.childSessionsByRoot, [rootSessionId]: sessions },
    childEventCursorByRoot: { ...state.childEventCursorByRoot, [rootSessionId]: cursor },
    childEventGapByRoot: { ...state.childEventGapByRoot, [rootSessionId]: false },
    childLastSeqBySession: Object.fromEntries(
      Object.entries(state.childLastSeqBySession).filter(
        ([key]) => !key.startsWith(`${rootSessionId}:`)
      )
    )
  }
}

export interface PersistedSessionEvent {
  seq: number
  method: string
  params: Record<string, unknown>
}

/**
 * Rebuild ordinary task state after a renderer/appserver reconnect.
 *
 * The appserver deliberately does not persist prompt text, so this replay is
 * limited to redacted protocol events.  A gap is recorded for the caller to
 * request an authoritative replay from cursor zero; it is never silently
 * converted into a complete-looking task.
 */
export function replaySessionEvents(
  state: ConversationState,
  sessionId: string,
  rawEvents: PersistedSessionEvent[],
  nextCursor: number,
  gapDetected: boolean
): ConversationState {
  const events = [...rawEvents]
    .filter((event) =>
      event.seq > (state.sessionEventCursorBySession[sessionId] ?? 0) &&
      event.method.startsWith('event/') &&
      event.params.session_id === sessionId
    )
    .sort((left, right) => left.seq - right.seq)
  const currentCursor = state.sessionEventCursorBySession[sessionId] ?? 0
  const replayed = events.reduce(
    (current, event) => applyProtocolNotification(current, event.method, event.params),
    state
  )
  return {
    ...replayed,
    sessionEventCursorBySession: {
      ...replayed.sessionEventCursorBySession,
      [sessionId]: Math.max(currentCursor, nextCursor, ...events.map((event) => event.seq))
    },
    sessionEventGapBySession: {
      ...replayed.sessionEventGapBySession,
      [sessionId]: gapDetected
    }
  }
}

export function applyProtocolNotification(
  state: ConversationState,
  method: string,
  params: unknown
): ConversationState {
  switch (method) {
    case 'event/message_delta': {
      const delta = params as MessageDelta
      return applyMessageDelta(state, delta.session_id, delta)
    }
    case 'event/final': {
      const final = params as FinalAnswer
      return applyFinalAnswer(state, final.session_id, final)
    }
    case 'event/job_status': {
      const job = params as JobStatusUpdate
      const runState = runStateFromJob(job.state)
      return {
        ...state,
        runningBySession: {
          ...state.runningBySession,
          [job.session_id]: isActiveRunState(runState)
        },
        runStateBySession: { ...state.runStateBySession, [job.session_id]: runState }
      }
    }
    case 'event/error': {
      const error = params as ErrorNotification
      return applyError(state, error.session_id, error.message)
    }
    case 'event/tool_begin': {
      const tool = params as ToolBegin
      return applyToolBegin(state, tool.session_id, tool)
    }
    case 'event/tool_end': {
      const tool = params as ToolEnd
      return applyToolEnd(state, tool.session_id, tool)
    }
    case 'event/done': {
      const done = params as RunComplete
      return applyRunComplete(state, done.session_id, done)
    }
    case 'event/plan': {
      const plan = params as { session_id: string; steps: string[] }
      return {
        ...state,
        planBySession: { ...state.planBySession, [plan.session_id]: [...plan.steps] }
      }
    }
    case 'event/step': {
      const step = params as { session_id: string; index: number; total: number; text: string }
      return {
        ...state,
        stepBySession: {
          ...state.stepBySession,
          [step.session_id]: { index: step.index, total: step.total, text: step.text }
        }
      }
    }
    case 'event/progress': {
      const progress = params as { session_id: string; text: string }
      return {
        ...state,
        progressBySession: { ...state.progressBySession, [progress.session_id]: progress.text }
      }
    }
    case 'event/team': {
      const team = params as { session_id: string; role?: string; stage?: string; phase?: string }
      const role = String(team.role ?? '')
      const stage = String(team.stage ?? '')
      const label = role && stage ? `[${role}] ${stage}` : role || stage || 'team'
      return {
        ...state,
        progressBySession: { ...state.progressBySession, [team.session_id]: label }
      }
    }
    case 'event/agent_routed': {
      const routed = params as { session_id: string; routing_reason?: string; payload?: { mode?: string } }
      const mode = String(routed.payload?.mode ?? '')
      const reason = String(routed.routing_reason ?? '')
      const label = [mode && `mode=${mode}`, reason].filter(Boolean).join(' ')
      return {
        ...state,
        progressBySession: { ...state.progressBySession, [routed.session_id]: label || 'routed' }
      }
    }
    case 'event/task_started': {
      const task = params as { session_id: string }
      return {
        ...state,
        runningBySession: { ...state.runningBySession, [task.session_id]: true },
        runStateBySession: { ...state.runStateBySession, [task.session_id]: 'running' }
      }
    }
    case 'event/task_complete': {
      const task = params as { session_id: string; ok: boolean }
      return {
        ...state,
        runningBySession: { ...state.runningBySession, [task.session_id]: false },
        runStateBySession: {
          ...state.runStateBySession,
          [task.session_id]: task.ok ? 'succeeded' : 'failed'
        }
      }
    }
    case 'event/token_usage': {
      const usage = params as Record<string, unknown>
      const sessionId = typeof usage.session_id === 'string' ? usage.session_id : ''
      return sessionId === '' ? state : applyTokenUsage(state, sessionId, usage)
    }
    case 'event/recovery_started':
    case 'event/recovery_analyzing':
    case 'event/recovery_attempt':
    case 'event/recovery_resolved':
    case 'event/recovery_exhausted':
      return applyRecoveryEvent(state, method, params as Record<string, unknown>)
    default:
      return method.startsWith('child_session/')
        ? applyChildSessionEvent(state, method, params as Record<string, unknown>)
        : state
  }
}

export function addApprovalRequest(
  state: ConversationState,
  request: ApprovalRequest
): ConversationState {
  if (state.approvals.some((item) => item.requestId === request.request_id)) {
    return state
  }
  const item: ApprovalRequestItem = {
    requestId: request.request_id,
    sessionId: request.session_id,
    riskLevel: request.risk_level,
    action: request.action,
    details: request.details,
    status: 'pending'
  }
  return { ...state, approvals: [...state.approvals, item] }
}

export function updateApprovalRequestStatus(
  state: ConversationState,
  requestId: string,
  status: ApprovalRequestStatus,
  error?: string
): ConversationState {
  const index = state.approvals.findIndex((item) => item.requestId === requestId)
  if (index < 0) return state
  const next = [...state.approvals]
  next[index] = {
    ...next[index]!,
    status,
    ...(error !== undefined ? { error } : {})
  }
  return { ...state, approvals: next }
}

export function removeApprovalRequest(
  state: ConversationState,
  requestId: string
): ConversationState {
  if (!state.approvals.some((item) => item.requestId === requestId)) return state
  return { ...state, approvals: state.approvals.filter((item) => item.requestId !== requestId) }
}

export function removeApprovalRequestsForSession(
  state: ConversationState,
  sessionId: string
): ConversationState {
  if (!state.approvals.some((item) => item.sessionId === sessionId)) return state
  return { ...state, approvals: state.approvals.filter((item) => item.sessionId !== sessionId) }
}
