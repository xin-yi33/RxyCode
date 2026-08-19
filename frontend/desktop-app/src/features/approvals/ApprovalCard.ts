import { createElement, type ReactElement } from 'react'
import { gx2VisualState } from './approval.mode.ts'

export interface ApprovalCardModel {
  requestId: string
  action: string
  path?: string
  risk: string
  runningInBackground?: boolean
}

export interface ApprovalCardProps {
  item: ApprovalCardModel | null
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  blockedReason?: string | null
  onAllow: (requestId: string) => void
  onDeny: (requestId: string) => void
  onCancel: (requestId: string) => void
}

export function ApprovalCard({
  item,
  loading = false,
  error = null,
  narrow = false,
  dark = false,
  blockedReason = null,
  onAllow,
  onDeny,
  onCancel
}: ApprovalCardProps): ReactElement {
  const visual = gx2VisualState({
    loading,
    error,
    empty: !loading && error === null && item === null,
    narrow,
    dark
  })
  return createElement(
    'article',
    {
      className: 'approval-card',
      'data-testid': 'approval-card',
      'data-visual-state': visual,
      'data-theme': dark ? 'dark' : 'light',
      'data-inline': 'true'
    },
    visual === 'loading' ? createElement('div', { 'data-testid': 'approval-card-loading' }, 'Loading') : null,
    visual === 'error' ? createElement('div', { role: 'alert', 'data-testid': 'approval-card-error' }, error) : null,
    visual === 'empty' ? createElement('p', { 'data-testid': 'approval-card-empty' }, 'No approval') : null,
    blockedReason
      ? createElement('p', { 'data-testid': 'approval-card-blocked' }, blockedReason)
      : null,
    item && visual !== 'loading' && visual !== 'error'
      ? createElement(
          'div',
          { className: 'approval-card-body', 'data-request-id': item.requestId, 'data-risk': item.risk },
          createElement('span', { className: 'approval-card-risk' }, item.risk),
          createElement('p', { className: 'approval-card-action' }, item.action),
          item.path ? createElement('p', { className: 'approval-card-path' }, item.path) : null,
          item.runningInBackground
            ? createElement('span', { className: 'approval-card-bg' }, 'running in background')
            : null,
          createElement(
            'div',
            { className: 'approval-card-actions' },
            createElement(
              'button',
              { type: 'button', 'data-action': 'allow', onClick: () => onAllow(item.requestId) },
              'Allow'
            ),
            createElement(
              'button',
              { type: 'button', 'data-action': 'deny', onClick: () => onDeny(item.requestId) },
              'Deny'
            ),
            createElement(
              'button',
              { type: 'button', 'data-action': 'cancel', onClick: () => onCancel(item.requestId) },
              'Cancel'
            )
          )
        )
      : null
  )
}
