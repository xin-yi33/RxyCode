export interface WorktreeView {
  threadId: string
  path: string
  dirty: boolean
}

export function worktreesIsolated(a: WorktreeView, b: WorktreeView): boolean {
  return a.threadId !== b.threadId && a.path !== b.path
}

export function confirmDestructive(dirty: boolean, action: 'delete' | 'prune' | 'handoff'): 'confirm' | 'proceed' {
  if (dirty) return 'confirm'
  return action === 'delete' ? 'confirm' : 'proceed'
}
