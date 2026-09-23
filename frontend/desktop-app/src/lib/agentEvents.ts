import { isDeclaredCapability } from '@rxycode/protocol-client'

export type AgentEventMethod =
  | 'agent_started'
  | 'agent_tool'
  | 'agent_progress'
  | 'agent_done'
  | 'agent_paused'
  | 'agent_cancelled'
  | 'agent_budget_exceeded'

export interface AgentEvent {
  method: AgentEventMethod
  agentId: string
}

export function reduceAgentEvents(
  capabilities: Record<string, unknown> | null,
  events: readonly AgentEvent[],
  incoming: AgentEvent
): AgentEvent[] {
  if (!isDeclaredCapability(capabilities, 'multi_agent')) return []
  return [...events, incoming]
}

export function multiAgentUiVisible(capabilities: Record<string, unknown> | null): boolean {
  return isDeclaredCapability(capabilities, 'multi_agent')
}
