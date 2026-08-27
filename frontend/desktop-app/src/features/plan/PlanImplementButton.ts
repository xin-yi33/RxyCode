import { createElement, type ReactElement } from 'react'

export function PlanImplementButton(props: {
  blocked: boolean
  onImplement: () => void
}): ReactElement {
  return createElement(
    'button',
    {
      type: 'button',
      'data-testid': 'plan-implement',
      disabled: props.blocked,
      onClick: props.onImplement
    },
    props.blocked ? 'BLOCKED_PREREQUISITE: plan/implement' : 'Implement'
  )
}
