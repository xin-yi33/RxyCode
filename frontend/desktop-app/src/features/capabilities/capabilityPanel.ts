import { isDeclaredCapability } from '@rxycode/protocol-client'

export function capabilityState(
  capabilities: Record<string, unknown> | null,
  name: string
): 'available' | 'degraded' {
  return isDeclaredCapability(capabilities, name) ? 'available' : 'degraded'
}
