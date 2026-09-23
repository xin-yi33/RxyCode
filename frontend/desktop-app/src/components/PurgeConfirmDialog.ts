import { createElement, useState, type ReactElement } from 'react'

export function PurgeConfirmDialog(props: {
  open: boolean
  backendError?: string | null
  onCancel: () => void
  onConfirm: () => void
}): ReactElement | null {
  const [secondStep, setSecondStep] = useState(false)
  if (!props.open) return null
  return createElement(
    'div',
    {
      className: 'purge-confirm-dialog',
      role: 'dialog',
      'aria-modal': 'true',
      'data-testid': 'purge-confirm-dialog',
      'data-step': secondStep ? 'second' : 'first'
    },
    createElement(
      'p',
      { 'data-testid': 'purge-risk-copy' },
      '将永久删除会话记录与关联文件'
    ),
    props.backendError
      ? createElement('p', { role: 'alert', 'data-testid': 'purge-backend-error' }, props.backendError)
      : null,
    createElement(
      'div',
      { className: 'purge-confirm-actions' },
      createElement(
        'button',
        {
          type: 'button',
          'data-action': 'cancel',
          autoFocus: true,
          onClick: () => {
            setSecondStep(false)
            props.onCancel()
          }
        },
        'Cancel'
      ),
      secondStep
        ? createElement(
            'button',
            { type: 'button', 'data-action': 'confirm-purge', onClick: props.onConfirm },
            'Confirm purge'
          )
        : createElement(
            'button',
            { type: 'button', 'data-action': 'continue-purge', onClick: () => setSecondStep(true) },
            'Continue'
          )
    )
  )
}
