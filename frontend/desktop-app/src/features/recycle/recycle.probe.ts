import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

/** B17 recycle contract. session/* is H5, not a substitute. */
export const B17_RECYCLE_METHODS = [
  'thread/list_deleted',
  'thread/restore',
  'thread/purge'
] as const

export function probeRecycle(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
} {
  const result = probeMethods(schemaText, B17_RECYCLE_METHODS)
  return {
    path: result.missing.length === 0 ? 'A' : 'B',
    present: result.present,
    missing: result.missing
  }
}

export function buildThreadRestore(
  schemaText: string,
  threadId: string
): { method: 'thread/restore'; params: { thread_id: string } } | ReturnType<typeof blockedPrerequisite> {
  const probe = probeRecycle(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'thread/restore', params: { thread_id: threadId } }
}

export function buildThreadPurge(
  schemaText: string,
  confirmPurge: boolean
):
  | { error: 'confirm_purge_required' }
  | { method: 'thread/purge'; params: { confirm_purge: true } }
  | ReturnType<typeof blockedPrerequisite> {
  if (!confirmPurge) return { error: 'confirm_purge_required' }
  const probe = probeRecycle(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'thread/purge', params: { confirm_purge: true } }
}

export function gx21VisualState(input: {
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
