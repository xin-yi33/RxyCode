import { createElement, type ReactElement } from 'react'
import { type SendIntent, gx5VisualState } from './pending.queue.ts'

export function SendDropdown(props: {
  running: boolean
  pendingCount: number
  error?: string | null
  narrow?: boolean
  dark?: boolean
  steerBlocked?: boolean
  onSend: (intent: SendIntent) => void
}): ReactElement {
  const visual = gx5VisualState({
    running: props.running,
    queueLength: props.pendingCount,
    error: props.error ?? null,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  if (!props.running) {
    return createElement(
      'button',
      {
        type: 'button',
        className: 'btn-primary',
        'data-testid': 'send-idle',
        'data-visual-state': visual,
        onClick: () => props.onSend('queue')
      },
      'Send'
    )
  }
  return createElement(
    'div',
    {
      className: 'send-menu',
      'data-testid': 'send-dropdown',
      'data-visual-state': visual,
      'data-pending': props.pendingCount
    },
    createElement(
      'button',
      {
        type: 'button',
        disabled: props.steerBlocked === true,
        onClick: () => props.onSend('steer')
      },
      props.steerBlocked ? 'Steer (BLOCKED_PREREQUISITE turn/steer)' : 'Steer with Message'
    ),
    createElement('button', { type: 'button', onClick: () => props.onSend('stop_and_send') }, 'Stop and Send'),
    createElement('button', { type: 'button', onClick: () => props.onSend('queue') }, 'Add to Queue')
  )
}
