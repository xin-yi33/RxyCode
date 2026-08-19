import { createElement, type ReactElement } from 'react'
import { probeMethods } from '../gx/schemaProbe.ts'
import type { NotifyTier } from '../../main/notifier.ts'

export function probeNeedsInput(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
  consumed: string[]
} {
  const invented = probeMethods(schemaText, ['event/agent_needs_input'])
  const existing = probeMethods(schemaText, ['approval/request', 'question/request', 'event/task_complete', 'event/final'])
  return {
    path: invented.present.length > 0 || existing.present.length > 0 ? 'A' : 'B',
    present: [...invented.present, ...existing.present],
    missing: invented.missing,
    consumed: existing.present
  }
}

export function NotificationSettings(props: {
  tier: NotifyTier
  onChange: (tier: NotifyTier) => void
}): ReactElement {
  return createElement(
    'fieldset',
    { 'data-testid': 'notification-settings' },
    (['off', 'unfocused', 'always'] as NotifyTier[]).map((tier) =>
      createElement(
        'label',
        { key: tier },
        createElement('input', {
          type: 'radio',
          name: 'notify-tier',
          checked: props.tier === tier,
          onChange: () => props.onChange(tier)
        }),
        tier
      )
    )
  )
}
