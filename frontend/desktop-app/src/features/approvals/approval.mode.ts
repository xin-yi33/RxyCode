/**
 * GX2-H: UI presets map onto B7 policies. Session mode is appserver-owned.
 * approval/mode_set is a design candidate — probe before sending anything.
 */
import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export type UIPreset = 'ask' | 'auto' | 'full'
export type B7Policy =
  | 'read_only'
  | 'workspace_write'
  | 'ask_for_each_risky_action'
  | 'allow_scoped_actions'
  | 'full_access'

export const MODE_SET_CANDIDATE = 'approval/mode_set'
export const PRESET_TO_B7: Record<UIPreset, B7Policy> = {
  ask: 'ask_for_each_risky_action',
  auto: 'allow_scoped_actions',
  full: 'full_access'
}

export const DEFAULT_PRESET: UIPreset = 'ask'
export const FULL_ACCESS_NOT_ENABLED = 'full_access_not_enabled'

export function mapPresetToB7(preset: UIPreset): B7Policy {
  return PRESET_TO_B7[preset]
}

export function probeModeSet(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
} {
  const result = probeMethods(schemaText, [MODE_SET_CANDIDATE])
  return {
    path: result.missing.length === 0 ? 'A' : 'B',
    ...result
  }
}

export function buildModeSetRequest(preset: UIPreset, schemaText: string): {
  method: string
  params: { preset: UIPreset }
} | ReturnType<typeof blockedPrerequisite> {
  const probe = probeModeSet(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: MODE_SET_CANDIDATE, params: { preset } }
}

export function rejectFullWithoutEnable(preset: UIPreset, fullEnabled: boolean): string | null {
  if (preset === 'full' && !fullEnabled) return FULL_ACCESS_NOT_ENABLED
  return null
}

export function approvalChannel(input: {
  risk: string
  preset: UIPreset
  action?: string
}): 'card' | 'modal' {
  const risk = input.risk.toUpperCase()
  const action = (input.action ?? '').toLowerCase()
  const highRisk =
    risk === 'DANGER' ||
    /\brm\b/.test(action) ||
    action.includes('delete') ||
    action.includes('.env')
  if (highRisk) return 'modal'
  if (input.preset === 'ask') return 'card'
  return 'modal'
}

export function sameRequestMutex(shown: { requestId: string; channel: 'card' | 'modal' } | null, requestId: string): boolean {
  return shown !== null && shown.requestId === requestId
}

export function gx2VisualState(input: {
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
