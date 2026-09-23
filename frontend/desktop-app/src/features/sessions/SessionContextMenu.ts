import {
  AppWindow,
  Archive,
  ChevronRight,
  Copy,
  Eye,
  FolderInput,
  List,
  Pencil,
  Pin,
  Share
} from 'lucide-react'
import { createElement, useEffect, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

export type SessionContextAction =
  | { kind: 'pin' }
  | { kind: 'rename' }
  | { kind: 'unread' }
  | { kind: 'archive' }
  | { kind: 'section'; section: 'pinned' | 'recent' }
  | { kind: 'share' }
  | { kind: 'copy'; field: 'title' | 'id' }
  | { kind: 'new-window' }

export interface SessionContextProject {
  cwd: string
  displayName: string
}

export function SessionContextMenu(props: {
  x: number
  y: number
  pinned: boolean
  unread: boolean
  sessionId: string
  title: string
  currentProject: string | null
  projects: readonly SessionContextProject[]
  labels: {
    pin: string
    unpin: string
    rename: string
    unread: string
    archive: string
    project: string
    section: string
    share: string
    copy: string
    copyTitle: string
    copyId: string
    openInNewWindow: string
    recent: string
  }
  onAction: (action: SessionContextAction) => void
  onClose: () => void
}): ReactElement {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [flyout, setFlyout] = useState<'project' | 'section' | 'share' | 'copy' | null>(null)
  const left = Math.max(8, Math.min(props.x, (typeof window === 'undefined' ? props.x : window.innerWidth) - 268))
  const top = Math.max(8, Math.min(props.y, (typeof window === 'undefined' ? props.y : window.innerHeight) - 380))

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

  const run = (action: SessionContextAction): void => {
    props.onAction(action)
    props.onClose()
  }

  const item = (
    key: string,
    icon: ReactElement,
    label: string,
    action: SessionContextAction | null,
    extra?: { shortcut?: string; submenu?: 'project' | 'section' | 'share' | 'copy'; testId?: string }
  ): ReactElement =>
    createElement(
      'button',
      {
        key,
        type: 'button',
        className: 'session-ctx-item' + (extra?.submenu !== undefined && flyout === extra.submenu ? ' is-open' : ''),
        'data-testid': extra?.testId,
        onMouseEnter: () => setFlyout(extra?.submenu ?? null),
        onClick: () => {
          if (action !== null) run(action)
        }
      },
      createElement('span', { className: 'session-ctx-icon' }, icon),
      createElement('span', { className: 'session-ctx-label' }, label),
      extra?.shortcut !== undefined
        ? createElement('kbd', { className: 'session-ctx-shortcut' }, extra.shortcut)
        : extra?.submenu !== undefined
          ? createElement(ChevronRight, { size: 14, className: 'session-ctx-caret', 'aria-hidden': true })
          : null
    )

  const flyoutPanel = (kind: 'project' | 'section' | 'share' | 'copy', children: ReactElement[]): ReactElement | null => {
    if (flyout !== kind) return null
    return createElement('div', { className: 'session-ctx-flyout', 'data-testid': `session-ctx-${kind}` }, children)
  }

  const menu = createElement(
    'div',
    {
      ref: rootRef,
      className: 'session-ctx',
      'data-testid': 'session-context-menu',
      style: { left, top },
      role: 'menu'
    },
    item('pin', createElement(Pin, { size: 15, 'aria-hidden': true }), props.pinned ? props.labels.unpin : props.labels.pin, { kind: 'pin' }, { shortcut: 'Alt+Ctrl+P', testId: 'ctx-pin' }),
    item('rename', createElement(Pencil, { size: 15, 'aria-hidden': true }), props.labels.rename, { kind: 'rename' }, { shortcut: 'Alt+Ctrl+R', testId: 'ctx-rename' }),
    item('unread', createElement(Eye, { size: 15, 'aria-hidden': true }), props.labels.unread, { kind: 'unread' }, { shortcut: 'Ctrl+Shift+U', testId: 'ctx-unread' }),
    item('archive', createElement(Archive, { size: 15, 'aria-hidden': true }), props.labels.archive, { kind: 'archive' }, { shortcut: 'Ctrl+Shift+A', testId: 'ctx-archive' }),
    createElement('div', { className: 'session-ctx-sep' }),
    createElement(
      'div',
      { className: 'session-ctx-has-flyout', onMouseEnter: () => setFlyout('project') },
      item('project', createElement(FolderInput, { size: 15, 'aria-hidden': true }), props.labels.project, null, { submenu: 'project' }),
      flyoutPanel(
        'project',
        props.projects.length === 0
          ? [createElement('p', { key: 'empty', className: 'session-ctx-empty' }, props.labels.project)]
          : props.projects.map((project) =>
              createElement(
                'button',
                {
                  key: project.cwd,
                  type: 'button',
                  className: 'session-ctx-item',
                  onClick: () => props.onClose()
                },
                createElement('span', { className: 'session-ctx-label' }, project.displayName),
                props.currentProject !== null && project.cwd === props.currentProject
                  ? createElement('span', { className: 'session-ctx-check' }, '✓')
                  : null
              )
            )
      )
    ),
    createElement(
      'div',
      { className: 'session-ctx-has-flyout', onMouseEnter: () => setFlyout('section') },
      item('section', createElement(List, { size: 15, 'aria-hidden': true }), props.labels.section, null, { submenu: 'section' }),
      flyoutPanel('section', [
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
    ),
    createElement('div', { className: 'session-ctx-sep' }),
    createElement(
      'div',
      { className: 'session-ctx-has-flyout', onMouseEnter: () => setFlyout('share') },
      item('share', createElement(Share, { size: 15, 'aria-hidden': true }), props.labels.share, null, { submenu: 'share', testId: 'ctx-share' }),
      flyoutPanel('share', [
        createElement(
          'button',
          { key: 'share-title', type: 'button', className: 'session-ctx-item', onClick: () => run({ kind: 'share' }) },
          createElement('span', { className: 'session-ctx-label' }, props.labels.copyTitle)
        )
      ])
    ),
    createElement(
      'div',
      { className: 'session-ctx-has-flyout', onMouseEnter: () => setFlyout('copy') },
      item('copy', createElement(Copy, { size: 15, 'aria-hidden': true }), props.labels.copy, null, { submenu: 'copy' }),
      flyoutPanel('copy', [
        createElement(
          'button',
          { key: 'title', type: 'button', className: 'session-ctx-item', onClick: () => run({ kind: 'copy', field: 'title' }) },
          createElement('span', { className: 'session-ctx-label' }, props.labels.copyTitle)
        ),
        createElement(
          'button',
          { key: 'id', type: 'button', className: 'session-ctx-item', onClick: () => run({ kind: 'copy', field: 'id' }) },
          createElement('span', { className: 'session-ctx-label' }, props.labels.copyId)
        )
      ])
    ),
    createElement('div', { className: 'session-ctx-sep' }),
    item('new-window', createElement(AppWindow, { size: 15, 'aria-hidden': true }), props.labels.openInNewWindow, { kind: 'new-window' }, { testId: 'ctx-new-window' })
  )

  if (typeof document === 'undefined' || document.body === null) return menu
  return createPortal(menu, document.body)
}
