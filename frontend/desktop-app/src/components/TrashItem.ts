import { createElement, type ReactElement } from 'react'
import { formatArchivedAt } from '../features/recycle/recycle.probe.ts'

export interface TrashItemModel {
  id: string
  title: string
  deletedAt: string
  originCategory: 'pinned' | 'project' | 'recent'
  workspaceRoot?: string
}

export function TrashItem(props: {
  item: TrashItemModel
  onRestore: (id: string) => void
  onPurge?: (id: string) => void
  unarchiveLabel?: string
  locale?: string
}): ReactElement {
  return createElement(
    'article',
    {
      className: 'trash-item archived-card',
      'data-testid': `trash-item-${props.item.id}`,
      'data-origin': props.item.originCategory
    },
    createElement('h3', { className: 'trash-item-title' }, props.item.title),
    createElement(
      'time',
      { dateTime: props.item.deletedAt, 'data-testid': 'trash-deleted-at' },
      formatArchivedAt(props.item.deletedAt, props.locale ?? 'zh-CN')
    ),
    createElement('span', { className: 'sr-only', 'data-testid': 'trash-origin' }, props.item.originCategory),
    createElement(
      'div',
      { className: 'archived-card-actions' },
      props.onPurge === undefined
        ? null
        : createElement(
            'button',
            {
              type: 'button',
              className: 'archived-purge',
              'data-action': 'purge-one',
              'data-testid': `purge-archived-${props.item.id}`,
              'aria-label': '删除',
              onClick: () => props.onPurge?.(props.item.id)
            },
            '🗑'
          ),
      createElement(
        'button',
        {
          type: 'button',
          className: 'archived-unarchive',
          'data-action': 'restore',
          'data-testid': `restore-task-${props.item.id}`,
          onClick: () => props.onRestore(props.item.id)
        },
        props.unarchiveLabel ?? '取消归档'
      )
    )
  )
}
