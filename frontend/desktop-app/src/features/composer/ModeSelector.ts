import { createElement, type ReactElement } from 'react'
import { MODE_TO_CAPABILITY, type ComposerCapabilityMode } from './mode.ts'

export function ModeSelector(props: {
  mode: ComposerCapabilityMode
  blocked: boolean
  onChange: (mode: ComposerCapabilityMode) => void
}): ReactElement {
  return createElement(
    'select',
    {
      'data-testid': 'mode-selector',
      'data-capability': MODE_TO_CAPABILITY[props.mode],
      'data-blocked': props.blocked ? 'true' : 'false',
      value: props.mode,
      onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
        props.onChange(event.target.value as ComposerCapabilityMode)
    },
    createElement('option', { value: 'ask' }, 'Ask'),
    createElement('option', { value: 'edit' }, 'Edit'),
    createElement('option', { value: 'agent' }, 'Agent')
  )
}
