import { multiAgentUiVisible } from '../../lib/agentEvents.ts'

export function teamMount(capabilities: Record<string, unknown> | null): 'hidden' | 'BLOCKED_PREREQUISITE' | 'ready' {
  if (!multiAgentUiVisible(capabilities)) return 'BLOCKED_PREREQUISITE'
  return 'ready'
}
