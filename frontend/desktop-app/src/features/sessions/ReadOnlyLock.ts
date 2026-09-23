import { createElement, type ReactElement } from 'react'
import { configLocked } from './sessionFilter.ts'

export function ReadOnlyLock(props: { status: string }): ReactElement {
  const locked = configLocked(props.status)
  return createElement(
    'div',
    {
      className: 'read-only-lock',
      'data-testid': 'read-only-lock',
      'data-locked': locked ? 'true' : 'false'
    },
    locked ? createElement('span', { className: 'running-badge' }, 'running') : null
  )
}
