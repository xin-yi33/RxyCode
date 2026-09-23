import {
  Archive,
  ChevronRight,
  FolderOpen,
  List,
  Pencil,
  Pin,
  SquareArrowOutUpRight,
  X
} from 'lucide-react'
import { createElement, useEffect, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

export type ProjectContextAction =
  | { kind: 'pin' }
  | { kind: 'edit'; name?: string }
  | { kind: 'section'; section: 'pinned' | 'recent' }
  | { kind: 'reveal' }
  | { kind: 'worktree' }
  | { kind: 'archive-chats' }
  | { kind: 'remove' }

export function ProjectContextMenu(props: {
  x: number
  y: number
  pinned: boolean
  labels: {
    pin: string
    unpin: string
    edit: string
    section: string
    reveal: string
    createWorktree: string
    archiveChats: string
    removeProject: string
    recent: string
  }
  onAction: (action: ProjectContextAction) => void
  onClose: () => void
}): ReactElement {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [flyout, setFlyout] = useState<'section' | null>(null)
  const left = Math.max(8, Math.min(props.x, (typeof window === 'undefined' ? props.x : window.innerWidth) - 280))
  const top = Math.max(8, Math.min(props.y, (typeof window === 'undefined' ? props.y : window.innerHeight) - 340))

  useEffect(() => {
    const onPointer = (event: MouseEvent): void => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) props.onClose()
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') props.onClose()
    }
    window.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [props])

  const run = (action: ProjectContextAction): void => {
    props.onAction(action)
    props.onClose()
  }

  const item = (
    key: string,
    icon: ReactElement,
    label: string,
    action: ProjectContextAction | null,
    extra?: { submenu?: 'section'; testId?: string; danger?: boolean }
  ): ReactElement =>
    createElement(
      'button',
      {
        key,
        type: 'button',
        className:
          'session-ctx-item' +
          (extra?.submenu !== undefined && flyout === extra.submenu ? ' is-open' : '') +
          (extra?.danger === true ? ' is-danger' : ''),
        'data-testid': extra?.testId,
        onMouseEnter: () => setFlyout(extra?.submenu ?? null),
        onClick: () => {
          if (action !== null) run(action)
        }
      },
      createElement('span', { className: 'session-ctx-icon' }, icon),
      createElement('span', { className: 'session-ctx-label' }, label),
      extra?.submenu !== undefined
        ? createElement(ChevronRight, { size: 14, className: 'session-ctx-caret', 'aria-hidden': true })
        : null
    )

  const menu = createElement(
    'div',
    {
      ref: rootRef,
      className: 'session-ctx',
      'data-testid': 'project-context-menu',
      style: { left, top },
      role: 'menu'
    },
    item('pin', createElement(Pin, { size: 15, 'aria-hidden': true }), props.pinned ? props.labels.unpin : props.labels.pin, { kind: 'pin' }, { testId: 'project-ctx-pin' }),
    item('edit', createElement(Pencil, { size: 15, 'aria-hidden': true }), props.labels.edit, { kind: 'edit' }, { testId: 'project-ctx-edit' }),
    createElement('div', { className: 'session-ctx-sep' }),
    createElement(
      'div',
      { className: 'session-ctx-has-flyout', onMouseEnter: () => setFlyout('section') },
      item('section', createElement(List, { size: 15, 'aria-hidden': true }), props.labels.section, null, { submenu: 'section', testId: 'project-ctx-section' }),
      flyout === 'section'
        ? createElement('div', { className: 'session-ctx-flyout', 'data-testid': 'project-ctx-section-flyout' }, [
            createElement(
              'button',
              { key: 'pinned', type: 'button', className: 'session-ctx-item', onClick: () => run({ kind: 'section', section: 'pinned' }) },
              createElement('span', { className: 'session-ctx-label' }, props.labels.pin)
            ),
            createElement(
              'button',
              { key: 'recent', type: 'button', className: 'session-ctx-item', onClick: () => run({ kind: 'section', section: 'recent' }) },
              createElement('span', { className: 'session-ctx-label' }, props.labels.recent)
            )
          ])
        : null
    ),
    item('reveal', createElement(FolderOpen, { size: 15, 'aria-hidden': true }), props.labels.reveal, { kind: 'reveal' }, { testId: 'project-ctx-reveal' }),
    item(
      'worktree',
      createElement(SquareArrowOutUpRight, { size: 15, 'aria-hidden': true }),
      props.labels.createWorktree,
      { kind: 'worktree' },
      { testId: 'project-ctx-worktree' }
    ),
    createElement('div', { className: 'session-ctx-sep' }),
    item('archive', createElement(Archive, { size: 15, 'aria-hidden': true }), props.labels.archiveChats, { kind: 'archive-chats' }, { testId: 'project-ctx-archive' }),
    createElement('div', { className: 'session-ctx-sep' }),
    item('remove', createElement(X, { size: 15, 'aria-hidden': true }), props.labels.removeProject, { kind: 'remove' }, { testId: 'project-ctx-remove', danger: true })
  )

  if (typeof document === 'undefined' || document.body === null) return menu
  return createPortal(menu, document.body)
}
