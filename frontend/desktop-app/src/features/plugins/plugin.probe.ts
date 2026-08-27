import {
  blockedPrerequisite,
  probeMethods,
  type BlockedClose,
  type ProbeOutcome
} from '../gx/schemaProbe.ts'

export const PLUGIN_METHODS = ['plugin/list', 'plugin/install', 'plugin/toggle', 'capability/set_enabled'] as const

export function probePlugins(schemaText: string): ProbeOutcome {
  const result = probeMethods(schemaText, PLUGIN_METHODS)
  return { path: result.present.some((name) => name.startsWith('plugin/')) ? 'A' : 'B', ...result }
}

export function buildPluginToggle(
  schemaText: string,
  id: string
): { method: 'plugin/toggle'; params: { id: string } } | BlockedClose {
  const probe = probePlugins(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'plugin/toggle', params: { id } }
}
