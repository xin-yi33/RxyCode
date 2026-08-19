/**
 * GX1-H: Thread → board column projection. No new status model.
 * Column membership is derived from H5 ThreadStatus / TurnStatus plus
 * the frozen GX1 example statuses. Unknown values fall into Active.
 */
import {
  type ThreadStatus,
  type TurnStatus
} from '../threads/threadProjection.ts'

export type BoardColumnId = 'drafts' | 'active' | 'ready' | 'done'

export interface BoardThread {
  id: string
  title: string
  updatedAt: number
  /** Raw status string used for the total-function mapper. */
  status: string
}

export interface BoardCard {
  id: string
  title: string
  updatedAt: number
  status: string
  column: BoardColumnId
  errorBadge: boolean
  timeoutBadge: boolean
  reviewEntry: boolean
}

export const BOARD_COLUMNS: readonly BoardColumnId[] = ['drafts', 'active', 'ready', 'done']

export const H5_THREAD_STATUSES: readonly ThreadStatus[] = ['active', 'archived', 'trashed']
export const H5_TURN_STATUSES: readonly TurnStatus[] = [
  'queued',
  'running',
  'waiting',
  'completed',
  'failed',
  'cancelled'
]

export const GX1_EXAMPLE_STATUSES = [
  'drafting',
  'running',
  'awaiting_review',
  'done',
  'failed',
  'cancelled',
  'blocked'
] as const

const STATUS_TO_COLUMN: Record<string, BoardColumnId> = {
  drafting: 'drafts',
  queued: 'drafts',
  running: 'active',
  active: 'active',
  awaiting_review: 'ready',
  waiting: 'ready',
  approval: 'ready',
  done: 'done',
  completed: 'done',
  succeeded: 'done',
  archived: 'done',
  failed: 'active',
  cancelled: 'active',
  blocked: 'active',
  trashed: 'active',
  timed_out: 'active'
}

const ERROR_STATUSES = new Set(['failed', 'cancelled', 'blocked', 'trashed'])
const TIMEOUT_STATUSES = new Set(['timed_out'])

export function mapStatusToColumn(status: string): BoardColumnId {
  return STATUS_TO_COLUMN[status] ?? 'active'
}

export function showErrorBadge(status: string): boolean {
  if (ERROR_STATUSES.has(status) || TIMEOUT_STATUSES.has(status)) return true
  return STATUS_TO_COLUMN[status] === undefined
}

export function showTimeoutBadge(status: string): boolean {
  return TIMEOUT_STATUSES.has(status)
}

export function canDragBetween(from: BoardColumnId, to: BoardColumnId): boolean {
  if (from === to) return true
  return (from === 'drafts' && to === 'active') || (from === 'active' && to === 'drafts')
}

export function columnAllowsDrag(column: BoardColumnId): boolean {
  return column === 'drafts' || column === 'active'
}

export function projectSessionToBoardStatus(input: {
  trashed: boolean
  runState?: string
  hasActivity?: boolean
}): string {
  if (input.trashed) return 'trashed'
  const run = input.runState
  if (run === 'running') return 'running'
  if (run === 'queued') return 'queued'
  if (run === 'approval') return 'awaiting_review'
  if (run === 'failed') return 'failed'
  if (run === 'cancelled') return 'cancelled'
  if (run === 'timed_out') return 'timed_out'
  if ((run === 'succeeded' || run === 'completed') && input.hasActivity) return 'done'
  return 'drafting'
}

export function toBoardCard(thread: BoardThread): BoardCard {
  const column = mapStatusToColumn(thread.status)
  return {
    id: thread.id,
    title: thread.title,
    updatedAt: thread.updatedAt,
    status: thread.status,
    column,
    errorBadge: showErrorBadge(thread.status),
    timeoutBadge: showTimeoutBadge(thread.status),
    reviewEntry: column === 'ready'
  }
}

export function selectBoardColumns(
  threads: readonly BoardThread[]
): Record<BoardColumnId, BoardCard[]> {
  const columns: Record<BoardColumnId, BoardCard[]> = {
    drafts: [],
    active: [],
    ready: [],
    done: []
  }
  for (const thread of threads) {
    const card = toBoardCard(thread)
    columns[card.column].push(card)
  }
  return columns
}

export function sessionsToBoardThreads(
  sessions: readonly {
    sessionId: string
    title: string
    updatedAt: number
    trashedAt: number | null
  }[],
  runStateBySession: Readonly<Record<string, string>> = {},
  activityBySession: Readonly<Record<string, boolean>> = {}
): BoardThread[] {
  return sessions.map((session) => ({
    id: session.sessionId,
    title: session.title,
    updatedAt: session.updatedAt,
    status: projectSessionToBoardStatus({
      trashed: session.trashedAt !== null,
      runState: runStateBySession[session.sessionId],
      hasActivity: activityBySession[session.sessionId] === true
    })
  }))
}
