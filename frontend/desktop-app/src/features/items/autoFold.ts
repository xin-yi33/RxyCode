export type ToolCardStatus =
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | 'waiting_approval'

export interface ToolItem {
  id: string
  tool: string
  status: ToolCardStatus
  durationMs?: number
  argsSummary?: string
  referencesDiff?: boolean
}

export function shouldAutoFold(item: ToolItem, foldEnabled: boolean): boolean {
  if (!foldEnabled) return false
  if (item.status !== 'success') return false
  return item.referencesDiff !== true
}

export function todoState(status: 'pending' | 'running' | 'done'): 'empty' | 'spin' | 'check' {
  if (status === 'running') return 'spin'
  if (status === 'done') return 'check'
  return 'empty'
}

export const TOOL_BADGE_COLOR: Record<ToolCardStatus, string> = {
  running: 'var(--board-active)',
  success: 'var(--board-done)',
  failed: 'var(--board-error)',
  cancelled: 'var(--board-draft)',
  timeout: 'var(--board-timeout)',
  waiting_approval: 'var(--board-applying)'
}

export function gx6VisualState(input: {
  loading: boolean
  error: string | null
  empty: boolean
  narrow: boolean
  dark: boolean
}): 'loading' | 'error' | 'empty' | 'narrow' | 'dark' | 'ok' {
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
