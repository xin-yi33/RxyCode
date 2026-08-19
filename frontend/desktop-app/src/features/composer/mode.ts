import { probeMethods } from '../gx/schemaProbe.ts'

export type ComposerCapabilityMode = 'ask' | 'edit' | 'agent'
export type InvokeCapability = 'no_tools' | 'edit_only' | 'full'

export const MODE_TO_CAPABILITY: Record<ComposerCapabilityMode, InvokeCapability> = {
  ask: 'no_tools',
  edit: 'edit_only',
  agent: 'full'
}

export function probeCapabilityField(schemaText: string): { presentOnInvoke: boolean; presentOnPrompt: boolean } {
  const methods = probeMethods(schemaText, ['agent/invoke', 'session/prompt'])
  const hasField = /"capability"/.test(schemaText)
  return {
    presentOnInvoke: methods.present.includes('agent/invoke') && hasField,
    presentOnPrompt: methods.present.includes('session/prompt') && hasField
  }
}

export function attachCapability(
  schemaText: string,
  mode: ComposerCapabilityMode,
  target: 'agent/invoke' | 'session/prompt'
): { capability: InvokeCapability } | { status: 'BLOCKED_PREREQUISITE'; missing: string[] } {
  const probe = probeCapabilityField(schemaText)
  const ok = target === 'agent/invoke' ? probe.presentOnInvoke : probe.presentOnPrompt
  if (!ok) {
    return { status: 'BLOCKED_PREREQUISITE', missing: [`${target}.capability`] }
  }
  return { capability: MODE_TO_CAPABILITY[mode] }
}

export function planOverridesWrite(planMode: boolean, _capability: InvokeCapability): 'plan' | 'capability' {
  if (planMode) return 'plan'
  return 'capability'
}
