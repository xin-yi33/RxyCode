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

export function isolateProjectCwds(projects: readonly ProjectRecord[]): boolean {
  const seen = new Set<string>()
  for (const project of projects) {
    const key = project.cwd.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
  }
  return true
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
