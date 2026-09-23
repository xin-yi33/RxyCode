import { createElement, type ReactElement } from 'react'
import { SETTINGS_SECTIONS } from '../../lib/settingsSections.ts'

export function SettingsShell(): ReactElement {
  return createElement(
    'nav',
    { 'data-testid': 'settings-shell' },
    SETTINGS_SECTIONS.map((section) =>
      createElement(
        'div',
        { key: section.id, 'data-section': section.id, 'data-blocked': section.blocked ? 'true' : 'false' },
        section.labelKey
      )
    )
  )
}
