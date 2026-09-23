import { createElement, useState, type ReactElement } from 'react'
import type { BoardCard } from './board.selectors.ts'
import { columnAllowsDrag } from './board.selectors.ts'
import { BOARD_STATUS_COLORS } from './boardVisualState.ts'

export interface TaskCardProps {
  card: BoardCard
  onOpen: (id: string) => void
  onRename?: (id: string) => void
  onCancel?: (id: string) => void
  onReview?: (id: string) => void
  onDragStart?: (card: BoardCard) => void
}

export function TaskCard({
  card,
  onOpen,
  onRename,
  onCancel,
  onReview,
  onDragStart
}: TaskCardProps): ReactElement {
  const [menuOpen, setMenuOpen] = useState(false)
  const draggable = columnAllowsDrag(card.column)
  return createElement(
    'article',
    {
      className: 'board-card',
      'data-testid': `board-card-${card.id}`,
      'data-column': card.column,
      'data-status': card.status,
      'data-error-badge': card.errorBadge ? 'true' : 'false',
      'data-timeout-badge': card.timeoutBadge ? 'true' : 'false',
      'data-draggable': draggable ? 'true' : 'false',
      draggable,
      onDragStart: (event: React.DragEvent<HTMLElement>) => {
        if (!draggable) {
          event.preventDefault()
          return
        }
        event.dataTransfer.setData('text/board-card-id', card.id)
        event.dataTransfer.setData('text/board-column', card.column)
        onDragStart?.(card)
      }
    },
    createElement(
      'button',
      { type: 'button', className: 'board-card-main', onClick: () => onOpen(card.id) },
      createElement('span', { className: 'board-card-title' }, card.title),
      createElement(
        'span',
        { className: 'board-card-meta' },
        createElement(
          'span',
          {
            className: 'board-status-badge',
            'data-column': card.column,
            style: { background: BOARD_STATUS_COLORS[card.column] }
          },
          card.column
        ),
        card.errorBadge
          ? createElement(
              'span',
              { className: 'board-error-badge', style: { background: BOARD_STATUS_COLORS.error } },
              'Error'
            )
          : null,
        card.timeoutBadge
          ? createElement(
              'span',
              {
                className: 'board-timeout-badge',
                style: { background: BOARD_STATUS_COLORS.timeout }
              },
              'Timeout'
            )
          : null,
        createElement('time', { dateTime: new Date(card.updatedAt).toISOString() }, new Date(card.updatedAt).toLocaleString())
      )
    ),
    card.reviewEntry
      ? createElement(
          'button',
          {
            type: 'button',
            className: 'board-review-entry',
            'data-testid': `board-review-${card.id}`,
            onClick: () => onReview?.(card.id)
          },
          'Review'
        )
      : null,
    createElement(
      'div',
      { className: 'board-card-menu' },
      createElement(
        'button',
        {
          type: 'button',
          className: 'board-card-menu-toggle',
          'aria-label': 'Card menu',
          onClick: () => setMenuOpen((open) => !open)
        },
        '···'
      ),
      menuOpen
        ? createElement(
            'ul',
            { className: 'board-card-menu-list' },
            createElement(
              'li',
              null,
              createElement('button', { type: 'button', onClick: () => onOpen(card.id) }, 'Open')
            ),
            createElement(
              'li',
              null,
              createElement('button', { type: 'button', onClick: () => onRename?.(card.id) }, 'Rename')
            ),
            createElement(
              'li',
              null,
              createElement('button', { type: 'button', onClick: () => onCancel?.(card.id) }, 'Cancel')
            )
          )
        : null
    )
  )
}
