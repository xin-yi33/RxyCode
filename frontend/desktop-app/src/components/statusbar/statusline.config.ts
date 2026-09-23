export type StatuslineItemId = 'model' | 'context' | 'tokens' | 'git_branch' | 'task_progress' | 'cost'

export const STATUSLINE_ITEMS: readonly StatuslineItemId[] = [
  'model',
  'context',
  'tokens',
  'git_branch',
  'task_progress',
  'cost'
]

export const DEFAULT_STATUSLINE: readonly StatuslineItemId[] = ['model', 'context', 'tokens']

export function visibleStatuslineItems(
  enabled: readonly StatuslineItemId[],
  opts: { hasPricing: boolean; narrow: boolean }
): StatuslineItemId[] {
  const base = enabled.filter((id) => (id === 'cost' ? opts.hasPricing : true))
  if (opts.narrow) return base.filter((id) => id === 'model' || id === 'context')
  return base
}

export function contextWarn(used: number, limit: number): boolean {
  if (limit <= 0) return false
  return used / limit >= 0.5
}

export function usageRatio(used: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min(1, used / limit)
}

export function gx7VisualState(input: {
  hasSession: boolean
  loading: boolean
  error: string | null
  narrow: boolean
  dark: boolean
}): 'hidden' | 'loading' | 'error' | 'narrow' | 'dark' | 'ok' {
  if (!input.hasSession) return 'hidden'
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
