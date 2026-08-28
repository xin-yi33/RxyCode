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

export function steerRequestParams(
  sessionId: string,
  text: string
): { session_id: string; text: string } | null {
  const session_id = sessionId.trim()
  const trimmed = text.trim()
  if (session_id === '' || trimmed === '') return null
  return { session_id, text: trimmed }
}

export function buildSteer(
  schemaText: string,
  text: string,
  sessionId: string
):
  | { method: 'turn/steer'; params: { session_id: string; text: string } }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeSteer(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  const params = steerRequestParams(sessionId, text)
  if (params === null) return blockedPrerequisite(['session_id'])
  return { method: 'turn/steer', params }
}

export function buildStopAndSend(
  schemaText: string,
  sessionId: string
):
  | { method: 'session/interrupt'; params: { session_id: string } }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeSteer(schemaText)
  if (probe.stopMethod === null) return blockedPrerequisite(['session/interrupt'])
  const session_id = sessionId.trim()
  if (session_id === '') return blockedPrerequisite(['session_id'])
  return { method: 'session/interrupt', params: { session_id } }
}
