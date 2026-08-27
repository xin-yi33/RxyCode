export type BoardVisualState = 'loading' | 'error' | 'empty' | 'narrow' | 'dark' | 'ok'

export function boardVisualState(input: {
  loading: boolean
  error: string | null
  empty: boolean
  narrow: boolean
  dark: boolean
}): BoardVisualState {
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}

/** §1-9 status colors. Tokens, not per-card hex in components. */
export const BOARD_STATUS_COLORS = {
  drafts: 'var(--board-draft)',
  active: 'var(--board-active)',
  ready: 'var(--board-ready)',
  applying: 'var(--board-applying)',
  done: 'var(--board-done)',
  error: 'var(--board-error)',
  timeout: 'var(--board-timeout)'
} as const
