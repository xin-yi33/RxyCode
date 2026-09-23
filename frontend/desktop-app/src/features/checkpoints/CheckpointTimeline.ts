import { createElement, type ReactElement } from 'react'
import { gx4VisualState } from './checkpoint.probe.ts'

export interface CheckpointPoint {
  checkpointId: string
  seq: number
  name?: string
  createdAt: string
}

export function CheckpointTimeline(props: {
  points: readonly CheckpointPoint[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  onSelect: (id: string) => void
}): ReactElement {
  const visual = gx4VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.points.length === 0,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'ol',
    {
      className: 'checkpoint-timeline',
      'data-testid': 'checkpoint-timeline',
      'data-visual-state': visual,
      'data-theme': props.dark ? 'dark' : 'light'
    },
    visual === 'empty' ? createElement('li', { 'data-testid': 'checkpoint-empty' }, 'No checkpoints') : null,
    visual === 'error' ? createElement('li', { role: 'alert' }, props.error) : null,
    ...props.points.map((point) =>
      createElement(
        'li',
        { key: point.checkpointId, 'data-named': point.name ? 'true' : 'false' },
        createElement(
          'button',
          { type: 'button', onClick: () => props.onSelect(point.checkpointId) },
          point.name ?? `cp-${point.seq}`
        )
      )
    )
  )
}
