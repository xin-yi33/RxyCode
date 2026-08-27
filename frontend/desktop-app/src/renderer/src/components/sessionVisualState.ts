export function sessionVisualState(input: {
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
