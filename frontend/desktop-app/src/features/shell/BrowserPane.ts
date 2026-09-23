import { createElement, useState, type ReactElement } from 'react'

export function BrowserPane(props: { initialUrl?: string }): ReactElement {
  const [draft, setDraft] = useState(props.initialUrl ?? 'https://')
  const [url, setUrl] = useState(props.initialUrl ?? '')
  return createElement(
    'section',
    { className: 'right-pane', 'data-testid': 'right-view-browser' },
    createElement('header', { className: 'right-pane-head' }, '浏览器'),
    createElement(
      'form',
      {
        className: 'browser-url-row',
        onSubmit: (event: { preventDefault: () => void }) => {
          event.preventDefault()
          const next = draft.trim()
          setUrl(next.startsWith('http://') || next.startsWith('https://') ? next : `https://${next}`)
        }
      },
      createElement('input', {
        value: draft,
        'data-testid': 'browser-url',
        'aria-label': 'URL',
        onChange: (event: { target: { value: string } }) => setDraft(event.target.value)
      }),
      createElement('button', { type: 'submit', 'data-testid': 'browser-go' }, '转到')
    ),
    url === ''
      ? createElement('p', { className: 'right-panel-empty' }, '输入地址后打开页面')
      : createElement('iframe', {
          className: 'browser-frame',
          title: 'browser',
          src: url,
          sandbox: 'allow-scripts allow-same-origin allow-forms allow-popups',
          'data-testid': 'browser-frame'
        })
  )
}
