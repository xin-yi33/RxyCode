import { createElement, type ReactElement } from 'react'
import { todoState } from './autoFold.ts'

export interface TodoStep {
  id: string
  title: string
  status: 'pending' | 'running' | 'done'
}

export function TodoTimeline(props: { steps: readonly TodoStep[] }): ReactElement {
  return createElement(
    'ol',
    { className: 'todo-timeline', 'data-testid': 'todo-timeline' },
    props.steps.length === 0
      ? createElement('li', { 'data-testid': 'todo-empty' }, 'No todos')
      : props.steps.map((step) =>
          createElement(
            'li',
            { key: step.id, 'data-todo': todoState(step.status) },
            step.title
          )
        )
  )
}
