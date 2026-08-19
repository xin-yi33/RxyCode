export function gx28VisualState(input: {
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

export interface TeamGroup {
  id: string
  name: string
  builtin?: boolean
}

export interface TeamRecord {
  id: string
  name: string
  groupId: string
  description?: string
  disableModelInvocation?: boolean
}
