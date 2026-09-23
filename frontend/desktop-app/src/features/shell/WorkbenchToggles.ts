import { Folder, Globe, MessageSquare, PanelBottom, PanelRight, Plus, ScanSearch, Terminal, X } from 'lucide-react'
import { createElement, useState, type ReactElement } from 'react'

export type RightPanelDestination = 'review' | 'terminal' | 'browser' | 'files' | 'sidechat'
export type RightPanelView = RightPanelDestination | 'picker'

const DESTINATIONS: Array<[RightPanelDestination, string, string, typeof ScanSearch]> = [
  ['review', '审查', 'Ctrl+Shift+G', ScanSearch],
  ['terminal', '终端', 'Ctrl+`', Terminal],
  ['browser', '浏览器', 'Ctrl+T', Globe],
  ['files', '文件', 'Ctrl+P', Folder],
  ['sidechat', '侧边聊天', 'Ctrl+Alt+S', MessageSquare]
]

export function WorkbenchToggles(props: {
  rightOpen: boolean
  bottomOpen: boolean
  onToggleRight: () => void
  onToggleBottom: () => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'workbench-toggles', 'data-testid': 'workbench-toggles' },
    createElement(
      'button',
      {
        type: 'button',
        className: 'icon-button' + (props.rightOpen ? ' is-active' : ''),
        'data-testid': 'toggle-right-panel',
        title: '显示/隐藏侧边面板 Ctrl+Alt+B',
        'aria-pressed': props.rightOpen,
        onClick: props.onToggleRight
      },
      createElement(PanelRight, { size: 17, 'aria-hidden': true })
    ),
    createElement(
      'button',
      {
        type: 'button',
        className: 'icon-button' + (props.bottomOpen ? ' is-active' : ''),
        'data-testid': 'toggle-bottom-panel',
        title: '切换底部面板显示 Ctrl+J',
        'aria-pressed': props.bottomOpen,
        onClick: props.onToggleBottom
      },
      createElement(PanelBottom, { size: 17, 'aria-hidden': true })
    )
  )
}

export function RightPanelMenu(props: {
  onChange: (view: RightPanelDestination) => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'right-panel-menu', 'data-testid': 'right-panel-menu' },
    DESTINATIONS.map(([id, label, shortcut, Icon]) =>
      createElement(
        'button',
        {
          key: id,
          type: 'button',
          'data-testid': `right-panel-${id}`,
          title: `${label} ${shortcut}`,
          onClick: () => props.onChange(id)
        },
        createElement(Icon, { size: 16, 'aria-hidden': true }),
        createElement('span', null, label),
        createElement('kbd', null, shortcut)
      )
    )
  )
}

export function terminalTabTitle(cwd: string): string {
  const trimmed = cwd.trim() === '' ? 'C:\\Users\\Administrator' : cwd
  const label = trimmed.length > 16 ? `${trimmed.slice(0, 14)}...` : trimmed
  return `管理员: ${label}`
}

export function BottomTerminal(props: { cwd?: string; onClose?: () => void }): ReactElement {
  const root = props.cwd !== undefined && props.cwd.trim() !== '' ? props.cwd : 'C:\\Users\\Administrator'
  const [tabs, setTabs] = useState([{ id: 'term-1', title: terminalTabTitle(root) }])
  const [activeId, setActiveId] = useState('term-1')
  return createElement(
    'section',
    { className: 'bottom-terminal', 'data-testid': 'bottom-terminal' },
    createElement(
      'header',
      { className: 'bottom-terminal-tabs' },
      tabs.map((tab) =>
        createElement(
          'button',
          {
            key: tab.id,
            type: 'button',
            className: 'bottom-terminal-tab' + (tab.id === activeId ? ' is-active' : ''),
            'data-testid': `bottom-terminal-tab-${tab.id}`,
            onClick: () => setActiveId(tab.id)
          },
          tab.title
        )
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: 'bottom-terminal-add',
          'data-testid': 'bottom-terminal-add',
          title: '新建终端',
          onClick: () => {
            const id = `term-${Date.now().toString(36)}`
            setTabs((current) => [...current, { id, title: terminalTabTitle(root) }])
            setActiveId(id)
          }
        },
        createElement(Plus, { size: 14, 'aria-hidden': true })
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: 'bottom-terminal-close',
          'data-testid': 'bottom-terminal-close',
          title: '关闭底部面板',
          onClick: () => props.onClose?.()
        },
        createElement(X, { size: 14, 'aria-hidden': true })
      )
    ),
    createElement(
      'pre',
      { className: 'bottom-terminal-body', 'data-testid': 'bottom-terminal-body' },
      `Windows PowerShell\n版权所有 (C) Microsoft Corporation。保留所有权利。\n\nPS ${root}> `
    )
  )
}

export function TerminalPane(): ReactElement {
  return createElement(
    'section',
    { className: 'right-pane', 'data-testid': 'right-view-terminal' },
    createElement('header', { className: 'right-pane-head' }, '终端'),
    createElement('pre', { className: 'right-terminal-body', 'data-testid': 'right-terminal-body' }, '$ ')
  )
}
