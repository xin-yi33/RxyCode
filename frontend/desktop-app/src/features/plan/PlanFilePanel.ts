import { createElement, type ReactElement } from 'react'
import { gx9VisualState } from './plan.persist.ts'
import { PlanImplementButton } from './PlanImplementButton.ts'

export function PlanFilePanel(props: {
  markdown: string
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  persistBlocked?: boolean
  implementBlocked?: boolean
  onChange: (markdown: string) => void
  onImplement: () => void
}): ReactElement {
  const visual = gx9VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.markdown.trim() === '',
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'section',
    {
      className: 'plan-file-panel',
      'data-testid': 'plan-file-panel',
      'data-visual-state': visual
    },
    props.persistBlocked
      ? createElement('p', { 'data-testid': 'plan-persist-blocked' }, 'BLOCKED_PREREQUISITE: plan/persist')
      : null,
    createElement('textarea', {
      value: props.markdown,
      onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => props.onChange(event.target.value)
    }),
    createElement(PlanImplementButton, { blocked: props.implementBlocked === true, onImplement: props.onImplement })
  )
}
