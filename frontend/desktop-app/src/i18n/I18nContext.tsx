import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { t as translate, type LocaleId } from './t.ts'

export interface I18nValue {
  locale: LocaleId
  t: (key: string, vars?: Record<string, string>) => string
}

const I18nContext = createContext<I18nValue>({
  locale: 'zh-CN',
  t: (key, vars = {}) => translate('zh-CN', key, vars)
})

export function I18nProvider({
  locale,
  children
}: {
  locale: LocaleId
  children: ReactNode
}): React.JSX.Element {
  const value = useMemo<I18nValue>(
    () => ({
      locale,
      t: (key, vars = {}) => translate(locale, key, vars)
    }),
    [locale]
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  return useContext(I18nContext)
}
