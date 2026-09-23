import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export const CHECKPOINT_CANDIDATES = [
  'checkpoint/snapshot/create',
  'checkpoint/rewind',
  'checkpoint/restore',
  'checkpoint/create',
  'checkpoint/list'
] as const

export function probeCheckpoints(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
} {
  const result = probeMethods(schemaText, CHECKPOINT_CANDIDATES)
  const needed = ['checkpoint/rewind', 'checkpoint/snapshot/create']
  const missingNeeded = needed.filter((name) => result.missing.includes(name))
  return {
    path: missingNeeded.length === 0 ? 'A' : 'B',
    present: result.present,
    missing: missingNeeded
  }
}

export function buildRewind(
  schemaText: string,
  checkpointId: string,
  confirm: boolean
):
  | { method: 'checkpoint/rewind'; params: { checkpoint_id: string; confirm: true } }
  | ReturnType<typeof blockedPrerequisite>
  | { error: 'confirm_required' } {
  if (!confirm) return { error: 'confirm_required' }
  const probe = probeCheckpoints(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'checkpoint/rewind', params: { checkpoint_id: checkpointId, confirm: true } }
}

export function gx4VisualState(input: {
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
