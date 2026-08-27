import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export const STEER_CANDIDATES = ['turn/steer', 'turn/interrupt', 'session/interrupt'] as const

export function probeSteer(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
  stopMethod: 'session/interrupt' | null
} {
  const result = probeMethods(schemaText, STEER_CANDIDATES)
  const stopMethod = result.present.includes('session/interrupt') ? 'session/interrupt' : null
  const steerMissing = !result.present.includes('turn/steer')
  return {
    path: steerMissing ? 'B' : 'A',
    present: result.present,
    missing: steerMissing ? ['turn/steer'] : [],
    stopMethod
  }
}

export function buildSteer(schemaText: string, text: string):
  | { method: 'turn/steer'; params: { text: string } }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeSteer(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'turn/steer', params: { text } }
}

export function buildStopAndSend(schemaText: string):
  | { method: 'session/interrupt'; params: Record<string, never> }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeSteer(schemaText)
  if (probe.stopMethod === null) return blockedPrerequisite(['session/interrupt'])
  return { method: 'session/interrupt', params: {} }
}
