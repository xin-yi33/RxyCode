import { createElement, type ReactElement } from 'react'
import { probeMethods } from '../gx/schemaProbe.ts'

export function probeRecycle(schemaText: string): { path: 'A' | 'B'; present: string[]; missing: string[] } {
  const result = probeMethods(schemaText, ['session/trash', 'session/restore', 'session/purge'])
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function RecycleBin(props: {
  items: readonly { id: string; title: string }[]
  onRestore: (id: string) => void
  onPurge: (id: string) => void
}): ReactElement {
  return createElement(
    'section',
    { 'data-testid': 'recycle-bin', 'data-visual-state': props.items.length === 0 ? 'empty' : 'ok' },
    props.items.map((item) =>
      createElement(
        'div',
        { key: item.id },
        item.title,
        createElement('button', { type: 'button', onClick: () => props.onRestore(item.id) }, 'Restore'),
        createElement('button', { type: 'button', onClick: () => props.onPurge(item.id) }, 'Purge')
      )
    )
  )
}
