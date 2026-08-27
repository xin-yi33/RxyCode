export type PermissionMode = 'confirm_all' | 'auto_edit' | 'full_auto'
export type ThemePreference = 'system' | 'light' | 'dark' | 'high-contrast'
export type DesktopLanguage = 'zh-CN' | 'en-US'

export interface DesktopPreferences {
  permissionMode: PermissionMode
  theme: ThemePreference
  language: DesktopLanguage
}

export const DESKTOP_PREFERENCES_STORAGE_KEY = 'rxycode.desktop.preferences.v1'
export const DEFAULT_DESKTOP_PREFERENCES: DesktopPreferences = {
  permissionMode: 'confirm_all',
  theme: 'dark',
  language: 'zh-CN'
}

export function loadDesktopPreferences(storage: Pick<Storage, 'getItem'>): DesktopPreferences {
  const raw = storage.getItem(DESKTOP_PREFERENCES_STORAGE_KEY)
  if (raw === null) return { ...DEFAULT_DESKTOP_PREFERENCES }
  try {
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null) throw new Error('not an object')
    const candidate = value as Record<string, unknown>
    if (
      (candidate.permissionMode !== 'confirm_all' &&
        candidate.permissionMode !== 'auto_edit' &&
        candidate.permissionMode !== 'full_auto') ||
      (candidate.theme !== 'system' &&
        candidate.theme !== 'light' &&
        candidate.theme !== 'dark' &&
        candidate.theme !== 'high-contrast') ||
      (candidate.language !== 'zh-CN' && candidate.language !== 'en-US')
    ) throw new Error('invalid preferences')
    return {
      permissionMode: candidate.permissionMode,
      theme: candidate.theme,
      language: candidate.language
    }
  } catch {
    return { ...DEFAULT_DESKTOP_PREFERENCES }
  }
}

export function saveDesktopPreferences(
  preferences: DesktopPreferences,
  storage: Pick<Storage, 'setItem'>
): void {
  storage.setItem(DESKTOP_PREFERENCES_STORAGE_KEY, JSON.stringify(preferences))
}
