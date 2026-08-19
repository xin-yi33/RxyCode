/**
 * PhaseG-H5: Thread/Turn/Item/Child Tree projection. UI never invents Threads.
 */

export type ThreadStatus = 'active' | 'archived' | 'trashed'
export type TurnStatus = 'queued' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled'

export interface ThreadRecord {
  sessionId: string
  title: string
  workspaceRoot: string
  projectId?: string
  status: ThreadStatus
  pinned?: boolean
  deletedAt?: string | null
  restoredAt?: string | null
  parentSessionId?: string | null
  cursor?: number
}

export interface ChildNode {
  sessionId: string
  parentSessionId: string
  agentId: string
  trigger: string
  status: TurnStatus
  durationMs?: number
  budget?: { used: number; limit: number }
  permission?: string
  failureReason?: string
}

export interface Draft {
  sessionId: string
  text: string
}

export function isDraftNotInput(draft: Draft): boolean {
  return draft.text.length > 0
}

export function filterThreads(
  threads: readonly ThreadRecord[],
  query: { projectId?: string; workspaceRoot?: string; status?: ThreadStatus }
): ThreadRecord[] {
  return threads.filter((thread) => {
    if (query.projectId !== undefined && thread.projectId !== query.projectId) return false
    if (query.workspaceRoot !== undefined && thread.workspaceRoot !== query.workspaceRoot) return false
    if (query.status !== undefined && thread.status !== query.status) return false
    return true
  })
}

export function restoreCursor(threads: readonly ThreadRecord[], sessionId: string): number {
  const hit = threads.find((thread) => thread.sessionId === sessionId)
  return hit?.cursor ?? 0
}

export function mergeChildTree(
  existing: readonly ChildNode[],
  incoming: ChildNode,
  eventId: string,
  seen: Readonly<Record<string, true>>
): { nodes: ChildNode[]; seen: Record<string, true> } {
  if (seen[eventId]) return { nodes: [...existing], seen: { ...seen } }
  return {
    nodes: [...existing.filter((node) => node.sessionId !== incoming.sessionId), incoming],
    seen: { ...seen, [eventId]: true }
  }
}

export function childDoesNotLeakIntoParent(
  parentItems: readonly { sessionId: string }[],
  child: ChildNode
): boolean {
  return parentItems.every((item) => item.sessionId !== child.sessionId)
}

export function confirmDelete(
  thread: ThreadRecord,
  confirmed: boolean,
  deletedAt: string
): { status: 'pending' | 'abort'; thread: ThreadRecord } | { status: 'soft-delete'; thread: ThreadRecord } {
  if (thread.sessionId.trim() === '') return { status: 'abort', thread }
  if (!confirmed) return { status: 'pending', thread }
  return {
    status: 'soft-delete',
    thread: { ...thread, status: 'trashed', deletedAt }
  }
}

export function createThread(sessionId: string, workspaceRoot: string, title: string): ThreadRecord {
  if (sessionId.trim() === '') {
    throw new Error('Thread id must come from backend session/new')
  }
  return {
    sessionId,
    title,
    workspaceRoot,
    status: 'active',
    cursor: 0
  }
}

export function renameThread(thread: ThreadRecord, title: string): ThreadRecord {
  return { ...thread, title }
}

export function archiveThread(thread: ThreadRecord): ThreadRecord {
  return { ...thread, status: 'archived' }
}

export function restoreThread(thread: ThreadRecord, restoredAt: string): ThreadRecord {
  return { ...thread, status: 'active', deletedAt: null, restoredAt }
}

export function forkThread(thread: ThreadRecord, newId: string): ThreadRecord {
  if (newId.trim() === '') {
    throw new Error('forked Thread id must come from backend thread/fork')
  }
  return {
    ...thread,
    sessionId: newId,
    parentSessionId: thread.sessionId,
    status: 'active',
    deletedAt: null,
    restoredAt: null,
    cursor: 0,
    pinned: false
  }
}

export function parentChildNav(threads: readonly ThreadRecord[], child: ChildNode): {
  parent: ThreadRecord | undefined
  childId: string
} {
  return {
    parent: threads.find((thread) => thread.sessionId === child.parentSessionId),
    childId: child.sessionId
  }
}

export function bumpCursor(thread: ThreadRecord, sequence: number): ThreadRecord {
  if (sequence <= (thread.cursor ?? 0)) return thread
  return { ...thread, cursor: sequence }
}

export function draftExcludedFromItems(draft: Draft, items: readonly { text: string }[]): boolean {
  return isDraftNotInput(draft) && items.every((item) => item.text !== draft.text)
}

export const THREAD_LIST_DELETED = 'thread/list_deleted'
export const THREAD_FORK = 'thread/fork'
