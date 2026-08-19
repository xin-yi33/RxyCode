import { createElement, type ReactElement } from 'react'
import {
  type UIPreset,
  mapPresetToB7,
  rejectFullWithoutEnable
} from './approval.mode.ts'

export interface PermissionModeSwitcherProps {
  preset: UIPreset
  fullEnabled: boolean
  blocked: boolean
  missingMethods?: readonly string[]
  narrow?: boolean
  dark?: boolean
  onRequestPreset: (preset: UIPreset) => void
}

const LABELS: Record<UIPreset, string> = {
  ask: 'Ask',
  auto: 'Auto-review',
  full: 'Full access'
}

export function PermissionModeSwitcher({
  preset,
  fullEnabled,
  blocked,
  missingMethods = [],
  narrow = false,
  dark = false,
  onRequestPreset
}: PermissionModeSwitcherProps): ReactElement {
  return createElement(
    'div',
    {
      className: 'permission-mode-switcher',
      'data-testid': 'permission-mode-switcher',
      'data-preset': preset,
      'data-policy': mapPresetToB7(preset),
      'data-blocked': blocked ? 'true' : 'false',
      'data-narrow': narrow ? 'true' : 'false',
      'data-theme': dark ? 'dark' : 'light'
    },
    blocked
      ? createElement(
          'span',
          { 'data-testid': 'mode-set-blocked' },
          `BLOCKED_PREREQUISITE: ${missingMethods.join(', ')}`
        )
      : createElement(
          'select',
          {
            'aria-label': 'Permission mode',
            value: preset,
            onChange: (event: React.ChangeEvent<HTMLSelectElement>) => {
              const next = event.target.value as UIPreset
              if (rejectFullWithoutEnable(next, fullEnabled)) return
              onRequestPreset(next)
            }
          },
          (Object.keys(LABELS) as UIPreset[]).map((id) =>
            createElement(
              'option',
              { key: id, value: id, disabled: id === 'full' && !fullEnabled },
              LABELS[id]
            )
          )
        )
  )
}
