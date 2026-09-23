/** Sessions without a picked project live under the CLI data dir, like Codex ~/.codex. */

export function normalizeWorkspacePath(root: string): string {
  return root.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function defaultRecentWorkspace(homeDir: string): string {
  const home = homeDir.replace(/\\/g, '/').replace(/\/+$/, '')
  if (home === '') return ''
  return `${home}/.RxyCode`
}

export function resolveRecentHome(homeDir: string, envHome = ''): string {
  const home = homeDir.trim() || envHome.trim()
  return defaultRecentWorkspace(home)
}

export function resolveCreateSessionWorkspace(input: {
  requested?: string | null
  homeDir?: string | null
  envHome?: string | null
  repoRoot?: string | null
}): string {
  const requested = (input.requested ?? '').trim()
  if (requested !== '') return requested
  return resolveRecentHome(input.homeDir ?? '', input.envHome ?? '')
}

export function isRecentWorkspace(root: string, recentHome: string): boolean {
  const normalized = normalizeWorkspacePath(root)
  if (normalized === '') return true
  const recent = normalizeWorkspacePath(recentHome)
  return normalized === recent || normalized.endsWith('/.rxycode')
}

export function looksRecentWorkspace(root: string): boolean {
  const normalized = normalizeWorkspacePath(root)
  return normalized === '' || normalized.endsWith('/.rxycode')
}

export function workspaceForNewChat(input: {
  selectedProject: string | null | undefined
  recentHome: string
}): string {
  const selected = (input.selectedProject ?? '').trim()
  if (selected !== '' && !isRecentWorkspace(selected, input.recentHome)) return selected
  return input.recentHome
}

export function composerProjectChip(input: {
  hasActiveSession: boolean
  activeWorkspace?: string | null
  draftWorkspace?: string | null
}): { visible: boolean; projectRoot?: string } {
  if (input.hasActiveSession) {
    const root = (input.activeWorkspace ?? '').trim()
    if (looksRecentWorkspace(root)) return { visible: false }
    return { visible: true, projectRoot: root }
  }
  const draft = (input.draftWorkspace ?? '').trim()
  if (draft !== '' && !looksRecentWorkspace(draft)) {
    return { visible: true, projectRoot: draft }
  }
  return { visible: true }
}
