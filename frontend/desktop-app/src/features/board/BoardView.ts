import { createElement, useState, type ReactElement } from 'react'
import {
  BOARD_COLUMNS,
  type BoardCard,
  type BoardColumnId,
  type BoardThread,
  canDragBetween,
  selectBoardColumns
} from './board.selectors.ts'
import { boardVisualState } from './boardVisualState.ts'
import { BoardColumn } from './BoardColumn.ts'

export interface BoardViewProps {
  threads: readonly BoardThread[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  onOpenThread: (id: string) => void
  onRenameThread?: (id: string) => void
  onCancelThread?: (id: string) => void
  onReviewThread?: (id: string) => void
  onMoveThread?: (id: string, from: BoardColumnId, to: BoardColumnId) => void
}

export function BoardView({
  threads,
  loading = false,
  error = null,
  narrow = false,
  dark = false,
  onOpenThread,
  onRenameThread,
  onCancelThread,
  onReviewThread,
  onMoveThread
}: BoardViewProps): ReactElement {
  const [draggingFrom, setDraggingFrom] = useState<BoardColumnId | null>(null)
  const visual = boardVisualState({
    loading,
    error,
    empty: !loading && error === null && threads.length === 0,
    narrow,
    dark
  })
  const columns = selectBoardColumns(threads)

  const handleDragStart = (card: BoardCard): void => {
    setDraggingFrom(card.column)
  }

  const handleDrop = (cardId: string, from: BoardColumnId, to: BoardColumnId): void => {
    setDraggingFrom(null)
    if (!canDragBetween(from, to) || from === to) return
    onMoveThread?.(cardId, from, to)
  }

  return createElement(
    'div',
    {
      className: 'board-view',
      'data-testid': 'board-view',
      'data-visual-state': visual,
      'data-theme': dark ? 'dark' : 'light'
    },
    visual === 'loading'
      ? createElement(
          'div',
          { className: 'board-skeleton', 'data-testid': 'board-loading' },
          BOARD_COLUMNS.map((id) =>
            createElement('div', { key: id, className: 'board-skeleton-col', 'data-column': id })
          )
        )
      : null,
    visual === 'error'
      ? createElement('div', { className: 'board-error', role: 'alert', 'data-testid': 'board-error' }, error)
      : null,
    visual === 'empty'
      ? createElement('p', { className: 'board-empty', 'data-testid': 'board-empty' }, 'No threads')
      : null,
    visual !== 'loading' && visual !== 'error' && visual !== 'empty'
      ? createElement(
          'div',
          { className: 'board-columns', 'data-narrow': narrow ? 'true' : 'false' },
          BOARD_COLUMNS.map((id) =>
            createElement(BoardColumn, {
              key: id,
              id,
              cards: columns[id],
              draggingFrom,
              onOpen: onOpenThread,
              onRename: onRenameThread,
              onCancel: onCancelThread,
              onReview: onReviewThread,
              onDragStart: handleDragStart,
              onDropCard: handleDrop
            })
          )
        )
      : null
  )
}
