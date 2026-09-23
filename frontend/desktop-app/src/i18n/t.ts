import zhCN from './locales/zh-CN.json' with { type: 'json' }
import en from './locales/en.json' with { type: 'json' }

export type LocaleId = 'zh-CN' | 'en'

export const LOCALE_TABLES: Record<LocaleId, Record<string, string>> = {
  'zh-CN': zhCN as Record<string, string>,
  en: en as Record<string, string>
}

export function normalizeLocale(raw: string | null | undefined): LocaleId {
  const value = (raw ?? '').toLowerCase()
  if (value.startsWith('zh')) return 'zh-CN'
  if (value.startsWith('en')) return 'en'
  return 'zh-CN'
}

export function t(locale: LocaleId, key: string, vars: Record<string, string> = {}): string {
  const table = LOCALE_TABLES[locale] ?? LOCALE_TABLES['zh-CN']
  let text = table[key] ?? LOCALE_TABLES['zh-CN'][key] ?? key
  for (const [name, value] of Object.entries(vars)) {
    text = text.replaceAll(`{${name}}`, value)
  }
  return text
}

export function isChatTextLocalized(_locale: LocaleId, modelReply: string): string {
  return modelReply
}

export function localeKeys(): string[] {
  return Object.keys(LOCALE_TABLES['zh-CN']).sort()
}
