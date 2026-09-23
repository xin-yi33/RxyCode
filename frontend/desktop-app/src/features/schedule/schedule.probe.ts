import {
  blockedPrerequisite,
  probeMethods,
  type BlockedClose,
  type ProbeOutcome
} from '../gx/schemaProbe.ts'

export const SCHEDULE_METHODS = ['schedule/list', 'schedule/create', 'schedule/delete'] as const

export function probeSchedule(schemaText: string): ProbeOutcome {
  const result = probeMethods(schemaText, SCHEDULE_METHODS)
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function buildScheduleCreate(
  schemaText: string
): { method: 'schedule/create'; params: Record<string, never> } | BlockedClose {
  const probe = probeSchedule(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'schedule/create', params: {} }
}
