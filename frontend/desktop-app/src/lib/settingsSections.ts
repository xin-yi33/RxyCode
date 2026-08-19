export type SettingsSectionId =
  | 'recycle'
  | 'general'
  | 'appearance'
  | 'models'
  | 'addModel'
  | 'skills'
  | 'mcp'
  | 'team'

export interface SettingsSection {
  id: SettingsSectionId
  labelKey: string
  blocked?: boolean
  lazy: true
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
  { id: 'recycle', labelKey: 'recycle', blocked: true, lazy: true },
  { id: 'general', labelKey: 'general', lazy: true },
  { id: 'appearance', labelKey: 'appearance', lazy: true },
  { id: 'models', labelKey: 'models', lazy: true },
  { id: 'addModel', labelKey: 'addModel', lazy: true },
  { id: 'skills', labelKey: 'skills', lazy: true },
  { id: 'mcp', labelKey: 'mcp', lazy: true },
  { id: 'team', labelKey: 'team', blocked: true, lazy: true }
]

export const SETTINGS_ENTRY = {
  borderRadiusPx: 6,
  iconPlusLabel: true
}

export function effortOptionsFor(model: { effort_options?: string[] } | null): string[] {
  return model?.effort_options ?? []
}

export const TEAM_SECTION_ALIGN = 'PHASE-H H10 three-level fold'
