import {
  blockedPrerequisite,
  probeMethods,
  type BlockedClose,
  type ProbeOutcome
} from '../gx/schemaProbe.ts'

export const CLI_METHODS = ['cli/list', 'cli/install', 'cli/launch'] as const

export function probeCli(schemaText: string): ProbeOutcome {
  const result = probeMethods(schemaText, CLI_METHODS)
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function buildCliLaunch(
  schemaText: string,
  id: string
): { method: 'cli/launch'; params: { id: string } } | BlockedClose {
  const probe = probeCli(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'cli/launch', params: { id } }
}
