import { createElement, type ReactElement } from 'react'
import type { BoardCard, BoardColumnId } from './board.selectors.ts'
import { canDragBetween } from './board.selectors.ts'
import { TaskCard } from './TaskCard.ts'

const COLUMN_LABEL: Record<BoardColumnId, string> = {
  drafts: 'Drafts',
  active: 'Active',
  ready: 'Ready',
  done: 'Done'
}

export interface BoardColumnProps {
  id: BoardColumnId
  cards: readonly BoardCard[]
  draggingFrom: BoardColumnId | null
  onOpen: (id: string) => void
  onRename?: (id: string) => void
  onCancel?: (id: string) => void
  onReview?: (id: string) => void
  onDragStart?: (card: BoardCard) => void
  onDropCard?: (cardId: string, from: BoardColumnId, to: BoardColumnId) => void
}

export function BoardColumn({
  id,
  cards,
  draggingFrom,
  onOpen,
  onRename,
  onCancel,
  onReview,
  onDragStart,
  onDropCard
}: BoardColumnProps): ReactElement {
  const dropAllowed = draggingFrom !== null && canDragBetween(draggingFrom, id)
  return createElement(
    'section',
    {
      className: 'board-column',
      'data-testid': `board-column-${id}`,
      'data-column': id,
      'data-count': cards.length,
      'data-drop-allowed': dropAllowed ? 'true' : 'false',
      onDragOver: (event: React.DragEvent<HTMLElement>) => {
        if (draggingFrom === null || !canDragBetween(draggingFrom, id)) return
        event.preventDefault()
      },
      onDrop: (event: React.DragEvent<HTMLElement>) => {
        event.preventDefault()
        const cardId = event.dataTransfer.getData('text/board-card-id')
        const from = event.dataTransfer.getData('text/board-column') as BoardColumnId
        if (!cardId || !from) return
        if (!canDragBetween(from, id)) return
        onDropCard?.(cardId, from, id)
      }
    },
    createElement(
      'header',
      { className: 'board-column-header' },
      createElement('h2', null, COLUMN_LABEL[id]),
      createElement('span', { className: 'board-column-count' }, String(cards.length))
    ),
    cards.length === 0
      ? createElement(
          'p',
          { className: 'board-column-empty', 'data-testid': `board-column-empty-${id}` },
          'No tasks'
        )
      : cards.map((card) =>
          createElement(TaskCard, {
            key: card.id,
            card,
            onOpen,
            onRename,
            onCancel,
            onReview,
            onDragStart
          })
        )
  )
}
