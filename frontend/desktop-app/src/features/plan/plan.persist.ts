import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export const PLAN_METHODS = ['plan/persist', 'plan/implement'] as const

export function probePlan(schemaText: string): { path: 'A' | 'B'; present: string[]; missing: string[] } {
  const result = probeMethods(schemaText, PLAN_METHODS)
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function planPath(threadId: string, slug: string, dataDir: string): string {
  return `${dataDir.replace(/\\/g, '/')}/plans/${threadId}-${slug}.md`
}

export function buildPersist(
  schemaText: string,
  payload: { threadId: string; markdown: string }
):
  | { method: 'plan/persist'; params: { thread_id: string; markdown: string } }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probePlan(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'plan/persist', params: { thread_id: payload.threadId, markdown: payload.markdown } }
}

export function gx9VisualState(input: {
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
