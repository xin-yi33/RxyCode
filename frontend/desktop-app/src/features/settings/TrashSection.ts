import { createElement, useState, type ReactElement } from 'react'
import { PurgeConfirmDialog } from '../../components/PurgeConfirmDialog.ts'
import { TrashItem, type TrashItemModel } from '../../components/TrashItem.ts'
import { gx21VisualState } from '../recycle/recycle.probe.ts'

export function TrashSection(props: {
  items: readonly TrashItemModel[]
  blocked: boolean
  missing: readonly string[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  backendError?: string | null
  onRestore: (id: string) => void
  onPurgeConfirmed: () => void
}): ReactElement {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const visual = gx21VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.items.length === 0,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'section',
    {
      className: 'trash-section',
      'data-testid': 'trash-section',
      'data-visual-state': visual,
      'data-blocked': props.blocked ? 'true' : 'false'
    },
    props.blocked
      ? createElement(
          'p',
          { 'data-testid': 'recycle-blocked' },
          `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}`
        )
      : null,
    visual === 'loading' ? createElement('p', { 'data-testid': 'trash-loading' }, 'Loading') : null,
    visual === 'error' ? createElement('p', { role: 'alert' }, props.error) : null,
    visual === 'empty' ? createElement('p', { 'data-testid': 'trash-empty' }, 'No deleted sessions') : null,
    ...props.items.map((item) =>
      createElement(TrashItem, { key: item.id, item, onRestore: props.onRestore })
    ),
    createElement(
      'button',
      {
        type: 'button',
        'data-action': 'open-purge',
        disabled: props.blocked,
        onClick: () => setConfirmOpen(true)
      },
      'Empty recycle bin'
    ),
    createElement(PurgeConfirmDialog, {
      open: confirmOpen,
      backendError: props.backendError ?? null,
      onCancel: () => setConfirmOpen(false),
      onConfirm: () => {
        setConfirmOpen(false)
        props.onPurgeConfirmed()
      }
    })
  )
}
