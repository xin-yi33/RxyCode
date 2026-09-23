import { Plus, X } from 'lucide-react'
import { createElement, useState, type ReactElement } from 'react'

export interface SideChatTab {
  id: string
  title: string
}

export function SideChatPanel(props: {
  blocked?: boolean
  missing?: readonly string[]
  tabs?: readonly SideChatTab[]
  activeId?: string | null
  messages?: readonly { role: 'user' | 'assistant'; text: string }[]
  onSelect?: (id: string) => void
  onRequestClose?: (id: string) => void
  onAdd?: () => void
  onSend?: (text: string) => void
  running?: boolean
}): ReactElement {
  const [draft, setDraft] = useState('')
  const tabs = props.tabs ?? []
  const messages = props.messages ?? []
  if (props.blocked === true) {
    return createElement(
      'aside',
      { 'data-testid': 'side-chat', 'data-blocked': 'true' },
      `BLOCKED_PREREQUISITE: ${(props.missing ?? []).join(', ')}`
    )
  }
  return createElement(
    'aside',
    { className: 'side-chat-panel', 'data-testid': 'side-chat', 'data-blocked': 'false' },
    createElement(
      'header',
      { className: 'side-chat-tabs' },
      tabs.map((tab) =>
        createElement(
          'button',
          {
            key: tab.id,
            type: 'button',
            className: 'side-chat-tab' + (props.activeId === tab.id ? ' is-active' : ''),
            'data-testid': `side-chat-tab-${tab.id}`,
            onClick: () => props.onSelect?.(tab.id)
          },
          createElement('span', null, tab.title),
          createElement(
            'span',
            {
              role: 'button',
              tabIndex: 0,
              className: 'side-chat-tab-close',
              'data-testid': `side-chat-close-${tab.id}`,
              onClick: (event: { stopPropagation: () => void }) => {
                event.stopPropagation()
                props.onRequestClose?.(tab.id)
              }
            },
            createElement(X, { size: 12, 'aria-hidden': true })
          )
        )
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: 'side-chat-add',
          'data-testid': 'side-chat-add',
          onClick: () => props.onAdd?.()
        },
        createElement(Plus, { size: 14, 'aria-hidden': true })
      )
    ),
    createElement(
      'div',
      { className: 'side-chat-messages' },
      tabs.length === 0 || messages.length === 0
        ? createElement(
            'p',
            { className: 'right-panel-empty', 'data-testid': 'side-chat-empty' },
            tabs.length === 0 ? '还没有侧边聊天，点 + 新建' : '在这里输入，开始侧边聊天'
          )
        : null,
      messages.map((message, index) =>
        createElement(
          'p',
          { key: `${message.role}-${index}`, className: `side-chat-${message.role}` },
          message.text
        )
      )
    ),
    createElement(
      'form',
      {
        className: 'side-chat-composer',
        onSubmit: (event: { preventDefault: () => void }) => {
          event.preventDefault()
          const text = draft.trim()
          if (text === '') return
          props.onSend?.(text)
          setDraft('')
        }
      },
      createElement('input', {
        value: draft,
        placeholder: '随心输入',
        'data-testid': 'side-chat-input',
        onChange: (event: { target: { value: string } }) => setDraft(event.target.value)
      }),
      props.running === true
        ? createElement('span', { className: 'side-chat-running', 'aria-hidden': true }, '■')
        : null
    )
  )
}
