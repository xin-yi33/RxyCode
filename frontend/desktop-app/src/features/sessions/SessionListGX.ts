import { createElement, type ReactElement, type ReactNode } from 'react'
import { SessionListFilter } from './SessionListFilter.ts'
import { type SessionFilterStatus } from './sessionFilter.ts'

export function SessionListGX(props: {
  status: SessionFilterStatus
  projectId: string
  onStatus: (status: SessionFilterStatus) => void
  onProject: (projectId: string) => void
  children: ReactNode
}): ReactElement {
  return createElement(
    'div',
    { className: 'session-list-gx', 'data-testid': 'session-list-gx' },
    createElement(SessionListFilter, {
      status: props.status,
      projectId: props.projectId,
      onStatus: props.onStatus,
      onProject: props.onProject
    }),
    props.children
  )
}
