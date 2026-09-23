import { createElement, type ReactElement } from 'react'
import { type SessionFilterStatus } from './sessionFilter.ts'

export function SessionListFilter(props: {
  status: SessionFilterStatus
  projectId: string
  onStatus: (status: SessionFilterStatus) => void
  onProject: (projectId: string) => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'session-list-filter', 'data-testid': 'session-list-filter' },
    createElement(
      'select',
      {
        'aria-label': 'Status filter',
        value: props.status,
        onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
          props.onStatus(event.target.value as SessionFilterStatus)
      },
      ['all', 'running', 'done', 'awaiting_review', 'archived'].map((value) =>
        createElement('option', { key: value, value }, value)
      )
    ),
    createElement('input', {
      'aria-label': 'Project filter',
      value: props.projectId,
      onChange: (event: React.ChangeEvent<HTMLInputElement>) => props.onProject(event.target.value)
    })
  )
}
