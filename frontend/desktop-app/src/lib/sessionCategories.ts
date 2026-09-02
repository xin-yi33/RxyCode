export type SessionCategory = 'pinned' | 'project' | 'recent'

export interface CategorizedSession {
  sessionId: string
  title: string
  workspaceRoot: string
  pinned?: boolean
  deletedAt?: string | null
  projectId?: string | null
}

export interface CategoryBuckets {
  pinned: CategorizedSession[]
  projects: Record<string, CategorizedSession[]>
  recent: CategorizedSession[]
  recycleBlocked: boolean
}

export function looksRecentWorkspace(root: string): boolean {
  const normalized = root.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
  return normalized === '' || normalized.endsWith('/.rxycode')
}

export const HOVER_LIGHT = 'rgba(0,0,0,0.06)'
export const HOVER_DARK = 'rgba(255,255,255,0.08)'
export const CHEVRON_GAP_PX = 4
export const PROJECT_SESSION_PREVIEW = 5

export function projectNeedsExpand(count: number, limit = PROJECT_SESSION_PREVIEW): boolean {
  return count > limit
}

export function visibleProjectSessions<T>(
  items: readonly T[],
  expanded: boolean,
  limit = PROJECT_SESSION_PREVIEW
): T[] {
  if (expanded || items.length <= limit) return [...items]
  return items.slice(0, limit)
}

export function projectCategories(
  sessions: readonly CategorizedSession[],
  listDeletedAvailable: boolean
): CategoryBuckets {
  const pinned: CategorizedSession[] = []
  const projects: Record<string, CategorizedSession[]> = {}
  const recent: CategorizedSession[] = []
  for (const session of sessions) {
    if (session.deletedAt) continue
    if (session.pinned) {
      pinned.push(session)
      continue
    }
    const projectKey = (session.projectId ?? session.workspaceRoot ?? '').trim()
    if (projectKey !== '' && !looksRecentWorkspace(projectKey)) {
      const list = projects[projectKey] ?? []
      list.push(session)
      projects[projectKey] = list
      continue
    }
    recent.push(session)
  }
  return { pinned, projects, recent, recycleBlocked: !listDeletedAvailable }
}

export function chevron(expanded: boolean): '>' | 'v' {
  return expanded ? 'v' : '>'
}
