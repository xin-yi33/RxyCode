import { createElement, type ReactElement } from 'react'

export function SchedulePanel(props: { blocked: boolean; missing: readonly string[] }): ReactElement {
  return createElement(
    'section',
    { 'data-testid': 'schedule-panel', 'data-blocked': props.blocked ? 'true' : 'false' },
    props.blocked ? `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}` : 'Schedules'
  )
}
