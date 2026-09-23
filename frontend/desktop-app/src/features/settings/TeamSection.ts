import { createElement, useState, type ReactElement } from 'react'
import { gx28VisualState } from '../team/team.visual.ts'

export const TEAM_AUTO_WARNING =
  '开启后系统将自动判断任务是否使用子代理/多 Agent 专家团并选择合适专家团；可能产生更多 token 消耗（实测 3–15x）。是否开启？'

export function TeamSection(props: {
  auto: boolean
  onAutoChange: (next: boolean) => void
  loading?: boolean
  error?: string | null
  empty?: boolean
  narrow?: boolean
  dark?: boolean
}): ReactElement {
  const [warnOpen, setWarnOpen] = useState(false)
  const visual = gx28VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.empty === true,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'section',
    {
      className: 'team-section',
      'data-testid': 'team-section',
      'data-visual-state': visual,
      'data-auto': props.auto ? 'on' : 'off'
    },
    createElement(
      'label',
      null,
      createElement('input', {
        type: 'checkbox',
        checked: props.auto,
        onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
          if (event.target.checked) setWarnOpen(true)
          else props.onAutoChange(false)
        }
      }),
      'Auto'
    ),
    warnOpen
      ? createElement(
          'div',
          { role: 'dialog', 'data-testid': 'team-auto-warning' },
          createElement('p', null, TEAM_AUTO_WARNING),
          createElement('button', { type: 'button', onClick: () => setWarnOpen(false) }, 'Cancel'),
          createElement(
            'button',
            {
              type: 'button',
              onClick: () => {
                setWarnOpen(false)
                props.onAutoChange(true)
              }
            },
            'Enable Auto'
          )
        )
      : null
  )
}
