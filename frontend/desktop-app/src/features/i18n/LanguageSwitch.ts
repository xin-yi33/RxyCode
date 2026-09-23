import { createElement, type ReactElement } from 'react'

export function LanguageSwitch(props: {
  locale: 'zh-CN' | 'en'
  onChange: (locale: 'zh-CN' | 'en') => void
}): ReactElement {
  return createElement(
    'select',
    {
      'data-testid': 'language-switch',
      value: props.locale,
      onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
        props.onChange(event.target.value as 'zh-CN' | 'en')
    },
    createElement('option', { value: 'zh-CN' }, '简体中文'),
    createElement('option', { value: 'en' }, 'English')
  )
}
