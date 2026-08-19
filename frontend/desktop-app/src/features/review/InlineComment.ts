import { createElement, useState, type ReactElement } from 'react'
import {
  gx3VisualState,
  type InlineCommentRecord
} from './review.comments.ts'

export function InlineComment(props: {
  file: string
  line: number
  hunkHash: string
  comments: readonly InlineCommentRecord[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  blockedReason?: string | null
  onAdd: (body: string) => void
  onResolve: (id: string) => void
}): ReactElement {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState('')
  const visual = gx3VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.comments.length === 0 && !open,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'div',
    {
      className: 'inline-comment',
      'data-testid': 'inline-comment',
      'data-line': props.line,
      'data-visual-state': visual,
      'data-theme': props.dark ? 'dark' : 'light'
    },
    createElement(
      'button',
      { type: 'button', className: 'anchor-btn', title: 'Add comment', onClick: () => setOpen(true) },
      '+'
    ),
    props.blockedReason
      ? createElement('p', { 'data-testid': 'review-comment-blocked' }, props.blockedReason)
      : null,
    ...props.comments.map((comment) =>
      createElement(
        'div',
        { key: comment.id, className: `comment ${comment.status}`, 'data-status': comment.status },
        createElement('p', null, comment.body),
        comment.status === 'stale' ? createElement('span', { className: 'badge' }, 'stale') : null,
        comment.status === 'open'
          ? createElement(
              'button',
              { type: 'button', onClick: () => props.onResolve(comment.id) },
              'Resolve'
            )
          : null
      )
    ),
    open
      ? createElement(
          'div',
          { className: 'comment-editor' },
          createElement('textarea', {
            value: body,
            onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => setBody(event.target.value)
          }),
          createElement(
            'button',
            {
              type: 'button',
              onClick: () => {
                props.onAdd(body)
                setOpen(false)
                setBody('')
              }
            },
            'Comment'
          )
        )
      : null
  )
}
