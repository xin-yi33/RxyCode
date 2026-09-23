import { createElement, type ReactElement } from 'react'

export function MessageRevertButton(props: {
  checkpointId: string
  fileCount: number
  messageCount: number
  blocked: boolean
  missing?: readonly string[]
  onConfirm: () => void
}): ReactElement {
  return createElement(
    'button',
    {
      type: 'button',
      className: 'message-revert',
      'data-testid': 'message-revert',
      'data-checkpoint': props.checkpointId,
      title: `Revert ${props.fileCount} files / ${props.messageCount} messages`,
      disabled: props.blocked,
      onClick: props.onConfirm
    },
    props.blocked ? `BLOCKED_PREREQUISITE: ${(props.missing ?? []).join(', ')}` : '↶'
  )
}
