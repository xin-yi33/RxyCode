import { createElement, type ReactElement, type ReactNode } from 'react'
import { SendDropdown } from './SendDropdown.ts'
import { shortcutIntent, type PendingItem, type SendIntent } from './pending.queue.ts'

/** Wrapper around the main-chain Composer. Does not edit H5 Composer.tsx. */
export function ComposerGX(props: {
  running: boolean
  pending: readonly PendingItem[]
  steerBlocked: boolean
  children: ReactNode
  onSend: (intent: SendIntent) => void
  onKeyIntent?: (intent: SendIntent) => void
}): ReactElement {
  return createElement(
    'div',
    {
      className: 'composer-gx',
      'data-testid': 'composer-gx',
      onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
        const intent = shortcutIntent(event)
        if (intent === null) return
        event.preventDefault()
        props.onKeyIntent?.(intent)
      }
    },
    props.children,
    createElement(SendDropdown, {
      running: props.running,
      pendingCount: props.pending.length,
      steerBlocked: props.steerBlocked,
      onSend: props.onSend
    })
  )
}
