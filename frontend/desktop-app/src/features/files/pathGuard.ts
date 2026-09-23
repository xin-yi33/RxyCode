/** PhaseG-H10: renderer does not decide workspace-outside access. */
export function isInsideWorkspace(workspaceRoot: string, target: string): boolean {
  const root = workspaceRoot.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
  const path = target.replace(/\\/g, '/').toLowerCase()
  return path === root || path.startsWith(`${root}/`)
}

export function interceptOutsidePath(workspaceRoot: string, target: string): string | null {
  if (isInsideWorkspace(workspaceRoot, target)) return null
  return `path is outside workspace: ${target}`
}
