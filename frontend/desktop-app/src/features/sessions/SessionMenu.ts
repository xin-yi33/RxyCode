import { createElement, type ReactElement } from 'react'

export function SessionMenu(props: {
  onRename: () => void
  onPin: () => void
  onArchive: () => void
  onSearch: () => void
  pinBlocked?: boolean
  archiveBlocked?: boolean
}): ReactElement {
  return createElement(
    'ul',
    { className: 'session-menu', 'data-testid': 'session-menu' },
    createElement('li', null, createElement('button', { type: 'button', onClick: props.onRename }, 'Rename')),
    createElement(
      'li',
      null,
      createElement(
        'button',
        { type: 'button', onClick: props.onPin, disabled: props.pinBlocked === true },
        props.pinBlocked ? 'Pin (BLOCKED_PREREQUISITE thread/pin)' : 'Pin'
      )
    ),
    createElement(
      'li',
      null,
      createElement(
        'button',
        { type: 'button', onClick: props.onArchive, disabled: props.archiveBlocked === true },
        props.archiveBlocked ? 'Archive (BLOCKED_PREREQUISITE thread/archive)' : 'Archive'
      )
    ),
    createElement('li', null, createElement('button', { type: 'button', onClick: props.onSearch }, 'Search'))
  )
}
