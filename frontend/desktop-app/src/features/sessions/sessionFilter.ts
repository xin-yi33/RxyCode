export type SessionFilterStatus = 'running' | 'done' | 'awaiting_review' | 'archived' | 'all'

export interface FilterableSession {
  id: string
  title: string
  projectId?: string
  status: Exclude<SessionFilterStatus, 'all'>
}

export function filterSessions(
  sessions: readonly FilterableSession[],
  query: { status: SessionFilterStatus; projectId?: string }
): FilterableSession[] {
  return sessions.filter((session) => {
    if (query.status !== 'all' && session.status !== query.status) return false
    if (query.projectId !== undefined && query.projectId !== '' && session.projectId !== query.projectId) {
      return false
    }
    return true
  })
}

export function groupByProject(sessions: readonly FilterableSession[]): Record<string, FilterableSession[]> {
  const groups: Record<string, FilterableSession[]> = {}
  for (const session of sessions) {
    const key = session.projectId ?? 'ungrouped'
    groups[key] = [...(groups[key] ?? []), session]
  }
  return groups
}

export function configLocked(status: string): boolean {
  return status === 'running'
}

export function composerKeptForQueue(status: string): boolean {
  return status === 'running' || status !== 'running'
}
