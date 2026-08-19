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

export const HOVER_LIGHT = 'rgba(0,0,0,0.06)'
export const HOVER_DARK = 'rgba(255,255,255,0.08)'
export const CHEVRON_GAP_PX = 4

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
    if (session.projectId) {
      const list = projects[session.projectId] ?? []
      list.push(session)
      projects[session.projectId] = list
      continue
    }
    recent.push(session)
  }
  return { pinned, projects, recent, recycleBlocked: !listDeletedAvailable }
}

export function chevron(expanded: boolean): '>' | 'v' {
  return expanded ? 'v' : '>'
}
