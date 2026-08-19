import { createElement, type ReactElement } from 'react'

export function PluginMarket(props: { blocked: boolean; missing: readonly string[] }): ReactElement {
  return createElement(
    'section',
    { 'data-testid': 'plugin-market', 'data-blocked': props.blocked ? 'true' : 'false' },
    props.blocked ? `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}` : 'Plugins'
  )
}
