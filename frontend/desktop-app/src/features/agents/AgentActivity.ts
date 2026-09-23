import { createElement, type ReactElement } from 'react'
import { multiAgentUiVisible, type AgentEvent } from '../../lib/agentEvents.ts'
import { probeMethods } from '../gx/schemaProbe.ts'

export function probeTeamEvents(schemaText: string): { path: 'A' | 'B'; present: string[] } {
  const result = probeMethods(schemaText, ['event/team', 'agents/delegate', 'agents/consult'])
  return { path: result.present.length > 0 ? 'A' : 'B', present: result.present }
}

export function AgentActivity(props: {
  capabilities: Record<string, unknown> | null
  events: readonly AgentEvent[]
}): ReactElement | null {
  if (!multiAgentUiVisible(props.capabilities)) {
    return createElement('div', { 'data-testid': 'agent-activity-hidden' }, 'capability undeclared')
  }
  return createElement(
    'ul',
    { 'data-testid': 'agent-activity' },
    props.events.map((event, index) =>
      createElement('li', { key: `${event.agentId}-${index}` }, `${event.agentId}:${event.method}`)
    )
  )
}
