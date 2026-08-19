import { localeKeys } from '../../i18n/t.ts'

export const GX22_REQUIRED = [
  'settings',
  'recycle',
  'boardView',
  'pinned',
  'projects',
  'recent',
  'language'
] as const

export function gx22CatalogComplete(keys: readonly string[] = localeKeys()): boolean {
  return GX22_REQUIRED.every((key) => keys.includes(key))
}
