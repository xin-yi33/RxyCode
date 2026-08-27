import { createElement, type ReactElement } from 'react'

export interface TrashItemModel {
  id: string
  title: string
  deletedAt: string
  originCategory: 'pinned' | 'project' | 'recent'
}

export function TrashItem(props: {
  item: TrashItemModel
  onRestore: (id: string) => void
}): ReactElement {
  return createElement(
    'article',
    {
      className: 'trash-item',
      'data-testid': `trash-item-${props.item.id}`,
      'data-origin': props.item.originCategory
    },
    createElement('h3', { className: 'trash-item-title' }, props.item.title),
    createElement('time', { dateTime: props.item.deletedAt, 'data-testid': 'trash-deleted-at' }, props.item.deletedAt),
    createElement('span', { 'data-testid': 'trash-origin' }, props.item.originCategory),
    createElement(
      'button',
      { type: 'button', 'data-action': 'restore', onClick: () => props.onRestore(props.item.id) },
      'Restore'
    )
  )
}
