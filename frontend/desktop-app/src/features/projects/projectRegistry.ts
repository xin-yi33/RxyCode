/**
 * PhaseG-H4: project list is a UI projection. Removing a project never
 * deletes user files. Two projects keep distinct cwd values.
 */

export interface ProjectRecord {
  id: string
  displayName: string
  cwd: string
  accessible: boolean
  pinned?: boolean
  error?: string
}

export const PROJECTS_STORAGE_KEY = 'rxycode.desktop.projects.v1'
export const HIDDEN_PROJECTS_STORAGE_KEY = 'rxycode.desktop.hiddenProjects.v1'

export function normalizeProjectCwd(cwd: string): string {
  return cwd.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function projectDisplayName(cwd: string): string {
  const cleaned = cwd.replace(/[\\/]+$/, '')
  const parts = cleaned.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] ?? cleaned
}

export function isolateProjectCwds(projects: readonly ProjectRecord[]): boolean {
  const seen = new Set<string>()
  for (const project of projects) {
    const key = normalizeProjectCwd(project.cwd)
    if (seen.has(key)) return false
    seen.add(key)
  }
  return true
}

export function matchProjectCwd(
  projects: readonly ProjectRecord[],
  cwd: string
): ProjectRecord | undefined {
  const key = normalizeProjectCwd(cwd)
  return projects.find((project) => normalizeProjectCwd(project.cwd) === key)
}

export function addProject(projects: readonly ProjectRecord[], cwd: string): ProjectRecord[] {
  const trimmed = cwd.trim()
  if (trimmed === '') return [...projects]
  if (matchProjectCwd(projects, trimmed) !== undefined) return [...projects]
  return [
    ...projects,
    {
      id: `proj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      displayName: projectDisplayName(trimmed),
      cwd: trimmed,
      accessible: true
    }
  ]
}

export function loadProjects(storage?: { getItem(key: string): string | null }): ProjectRecord[] {
  if (storage === undefined) return []
  try {
    const raw = storage.getItem(PROJECTS_STORAGE_KEY)
    if (raw === null || raw === '') return []
    const parsed = JSON.parse(raw) as ProjectRecord[]
    if (!Array.isArray(parsed)) return []
    return parsed.filter((project) => typeof project?.cwd === 'string' && project.cwd.trim() !== '')
  } catch {
    return []
  }
}

export function saveProjects(
  projects: readonly ProjectRecord[],
  storage?: { setItem(key: string, value: string): void }
): void {
  storage?.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(projects))
}

export function sidebarProjects(
  registered: readonly ProjectRecord[],
  sessionGroups: Record<string, readonly string[]>,
  hiddenCwds: readonly string[] = []
): Array<{ cwd: string; displayName: string; empty: boolean; registered: boolean; pinned: boolean }> {
  const rows: Array<{ cwd: string; displayName: string; empty: boolean; registered: boolean; pinned: boolean }> = []
  const seen = new Set<string>()
  const hiddenKeys = new Set(hiddenCwds.map((cwd) => normalizeProjectCwd(cwd)))
  for (const project of registered) {
    const key = normalizeProjectCwd(project.cwd)
    if (hiddenKeys.has(key)) continue
    seen.add(key)
    const sessions = Object.entries(sessionGroups).find(([cwd]) => normalizeProjectCwd(cwd) === key)?.[1] ?? []
    rows.push({
      cwd: project.cwd,
      displayName: project.displayName || projectDisplayName(project.cwd),
      empty: sessions.length === 0,
      registered: true,
      pinned: project.pinned === true
    })
  }
  for (const [cwd, sessions] of Object.entries(sessionGroups)) {
    const key = normalizeProjectCwd(cwd)
    if (seen.has(key) || hiddenKeys.has(key) || cwd.trim() === '') continue
    seen.add(key)
    rows.push({
      cwd,
      displayName: projectDisplayName(cwd),
      empty: sessions.length === 0,
      registered: false,
      pinned: false
    })
  }
  return [...rows.filter((row) => row.pinned), ...rows.filter((row) => !row.pinned)]
}

export function removeProject(
  projects: readonly ProjectRecord[],
  id: string
): { next: ProjectRecord[]; deletedFiles: false } {
  return {
    next: projects.filter((project) => project.id !== id),
    deletedFiles: false
  }
}

export function removeProjectByCwd(
  projects: readonly ProjectRecord[],
  cwd: string
): { next: ProjectRecord[]; deletedFiles: false } {
  const key = normalizeProjectCwd(cwd)
  return {
    next: projects.filter((project) => normalizeProjectCwd(project.cwd) !== key),
    deletedFiles: false
  }
}

export function renameProject(
  projects: readonly ProjectRecord[],
  cwd: string,
  displayName: string
): ProjectRecord[] {
  const key = normalizeProjectCwd(cwd)
  const nextName = displayName.trim()
  if (nextName === '') return [...projects]
  return projects.map((project) =>
    normalizeProjectCwd(project.cwd) === key ? { ...project, displayName: nextName } : project
  )
}

export function pinProject(
  projects: readonly ProjectRecord[],
  cwd: string,
  pinned: boolean
): ProjectRecord[] {
  const key = normalizeProjectCwd(cwd)
  return projects.map((project) =>
    normalizeProjectCwd(project.cwd) === key ? { ...project, pinned } : project
  )
}

export function hideProjectCwd(hidden: readonly string[], cwd: string): string[] {
  const key = normalizeProjectCwd(cwd)
  if (hidden.some((item) => normalizeProjectCwd(item) === key)) return [...hidden]
  return [...hidden, cwd]
}

export function unhideProjectCwd(hidden: readonly string[], cwd: string): string[] {
  const key = normalizeProjectCwd(cwd)
  return hidden.filter((item) => normalizeProjectCwd(item) !== key)
}

export function loadHiddenProjectCwds(storage?: { getItem(key: string): string | null }): string[] {
  if (storage === undefined) return []
  try {
    const raw = storage.getItem(HIDDEN_PROJECTS_STORAGE_KEY)
    if (raw === null || raw === '') return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : []
  } catch {
    return []
  }
}

export function saveHiddenProjectCwds(
  hidden: readonly string[],
  storage?: { setItem(key: string, value: string): void }
): void {
  storage?.setItem(HIDDEN_PROJECTS_STORAGE_KEY, JSON.stringify(hidden))
}

export function permanentWorktreeDest(cwd: string, stamp: string): string {
  return `${cwd.replace(/[\\/]+$/, '')}/.worktrees/wt-${stamp}`
}

export function inaccessibleProjectError(cwd: string, reason: string): string {
  return `workspace is not accessible: ${cwd} (${reason})`
}
