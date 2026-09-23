import { createElement, type ReactElement } from 'react'
import {
  gx6VisualState,
  shouldAutoFold,
  TOOL_BADGE_COLOR,
  type ToolItem
} from './autoFold.ts'

export function ToolCallCard(props: {
  item: ToolItem
  foldEnabled?: boolean
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  retryAvailable?: boolean
  onRetry?: (id: string) => void
}): ReactElement {
  const folded = shouldAutoFold(props.item, props.foldEnabled !== false)
  const visual = gx6VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: false,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'article',
    {
      className: 'tool-call-card',
      'data-testid': `tool-card-${props.item.id}`,
      'data-status': props.item.status,
      'data-folded': folded ? 'true' : 'false',
      'data-visual-state': visual
    },
    createElement(
      'header',
      null,
      createElement(
        'span',
        { className: 'tool-badge', style: { background: TOOL_BADGE_COLOR[props.item.status] } },
        props.item.status
      ),
      createElement('strong', null, props.item.tool),
      props.item.durationMs !== undefined
        ? createElement('span', { className: 'tool-duration' }, `${props.item.durationMs}ms`)
        : null
    ),
    folded
      ? createElement('summary', null, `✓ ${props.item.tool}`)
      : createElement('pre', null, props.item.argsSummary ?? ''),
    props.retryAvailable === true
      ? createElement(
          'button',
          { type: 'button', onClick: () => props.onRetry?.(props.item.id) },
          'auto-continue'
        )
      : null
  )
}
