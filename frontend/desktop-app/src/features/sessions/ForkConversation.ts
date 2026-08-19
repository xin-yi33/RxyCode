import { createElement, type ReactElement } from 'react'
import { canForkFrom } from './session.probe.ts'

export function ForkConversation(props: {
  role: string
  blocked: boolean
  onFork: () => void
}): ReactElement | null {
  if (!canForkFrom(props.role)) return null
  return createElement(
    'button',
    {
      type: 'button',
      'data-testid': 'fork-message',
      disabled: props.blocked,
      onClick: props.onFork
    },
    props.blocked ? 'BLOCKED_PREREQUISITE: thread/fork' : 'Fork'
  )
}
