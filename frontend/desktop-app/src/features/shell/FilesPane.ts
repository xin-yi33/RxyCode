import { FolderOpen } from 'lucide-react'
import { createElement, type ReactElement } from 'react'

const FILE_ARG_KEYS = ['path', 'file', 'filepath', 'target'] as const

export function knownFilesFromTimeline(
  items: readonly { kind?: string; arguments?: Record<string, unknown> }[]
): string[] {
  const files: string[] = []
  const seen = new Set<string>()
  for (const item of items) {
    const args = item.arguments
    if (args === undefined) continue
    for (const key of FILE_ARG_KEYS) {
      const value = args[key]
      if (typeof value !== 'string') continue
      const trimmed = value.trim()
      if (trimmed === '' || trimmed === '.' || trimmed === './' || trimmed === '/' || seen.has(trimmed)) continue
      seen.add(trimmed)
      files.push(trimmed)
    }
  }
  return files
}

export function FilesPane(props: {
  workspaceRoot: string | null
  files: readonly string[]
  onReveal: () => void
}): ReactElement {
  return createElement(
    'section',
    { className: 'right-pane', 'data-testid': 'right-view-files' },
    createElement('header', { className: 'right-pane-head' }, '文件'),
    createElement('p', { className: 'files-root', 'data-testid': 'files-root' }, props.workspaceRoot ?? '未选择工作区'),
    createElement(
      'button',
      {
        type: 'button',
        className: 'files-reveal',
        'data-testid': 'files-reveal',
        disabled: props.workspaceRoot === null || props.workspaceRoot === '',
        onClick: () => props.onReveal()
      },
      createElement(FolderOpen, { size: 14, 'aria-hidden': true }),
      '在资源管理器中打开'
    ),
      props.files.length === 0
        ? createElement('p', { className: 'right-panel-empty', 'data-testid': 'files-empty' }, '还没有文件变更')
        : createElement(
            'ul',
            { className: 'files-tree', 'data-testid': 'files-tree' },
            props.files.map((file) => createElement('li', { key: file, title: file }, file))
          )
  )
}
