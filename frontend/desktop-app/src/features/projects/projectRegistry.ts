/**
 * PhaseG-H4: project list is a UI projection. Removing a project never
 * deletes user files. Two projects keep distinct cwd values.
 */

export interface ProjectRecord {
  id: string
  displayName: string
  cwd: string
  accessible: boolean
  error?: string
}

export const PROJECTS_STORAGE_KEY = 'rxycode.desktop.projects.v1'

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
  sessionGroups: Record<string, readonly string[]>
): Array<{ cwd: string; displayName: string; empty: boolean; registered: boolean }> {
  const rows: Array<{ cwd: string; displayName: string; empty: boolean; registered: boolean }> = []
  const seen = new Set<string>()
  for (const project of registered) {
    const key = normalizeProjectCwd(project.cwd)
    seen.add(key)
    const sessions = Object.entries(sessionGroups).find(([cwd]) => normalizeProjectCwd(cwd) === key)?.[1] ?? []
    rows.push({
      cwd: project.cwd,
      displayName: project.displayName || projectDisplayName(project.cwd),
      empty: sessions.length === 0,
      registered: true
    })
  }
  for (const [cwd, sessions] of Object.entries(sessionGroups)) {
    const key = normalizeProjectCwd(cwd)
    if (seen.has(key) || cwd.trim() === '') continue
    seen.add(key)
    rows.push({
      cwd,
      displayName: projectDisplayName(cwd),
      empty: sessions.length === 0,
      registered: false
    })
  }
  return rows
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

export function inaccessibleProjectError(cwd: string, reason: string): string {
  return `workspace is not accessible: ${cwd} (${reason})`
}
