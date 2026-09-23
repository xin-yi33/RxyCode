import { createElement, type ReactElement } from 'react'

export function CloseSideChatDialog(props: {
  onCancel: () => void
  onConfirm: () => void
  dontAskAgain: boolean
  onDontAskAgain: (value: boolean) => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'sidechat-close-overlay', 'data-testid': 'close-side-chat', role: 'dialog' },
    createElement('button', { type: 'button', className: 'sheet-backdrop', 'aria-label': '取消', onClick: props.onCancel }),
    createElement(
      'div',
      { className: 'sidechat-close-dialog' },
      createElement('h2', null, '关闭侧边聊天?'),
      createElement('p', null, '这个侧边聊天将被删除，且无法恢复。你确定吗?'),
      createElement(
        'label',
        { className: 'sidechat-close-skip' },
        createElement('input', {
          type: 'checkbox',
          checked: props.dontAskAgain,
          onChange: (event: { target: { checked: boolean } }) => props.onDontAskAgain(event.target.checked)
        }),
        '不再询问'
      ),
      createElement(
        'footer',
        null,
        createElement('button', { type: 'button', onClick: props.onCancel }, '取消'),
        createElement(
          'button',
          { type: 'button', className: 'sidechat-close-confirm', 'data-testid': 'close-side-chat-confirm', onClick: props.onConfirm },
          '关闭侧边聊天'
        )
      )
    )
  )
}
