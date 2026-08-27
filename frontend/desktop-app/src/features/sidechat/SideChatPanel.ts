import { createElement, type ReactElement } from 'react'

export function SideChatPanel(props: { blocked: boolean; missing: readonly string[] }): ReactElement {
  return createElement(
    'aside',
    { 'data-testid': 'side-chat', 'data-blocked': props.blocked ? 'true' : 'false' },
    props.blocked ? `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}` : 'Side chat'
  )
}
