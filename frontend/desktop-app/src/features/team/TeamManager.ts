import { createElement, type ReactElement } from 'react'
import { probeMethods } from '../gx/schemaProbe.ts'

export function probeTeam(schemaText: string) {
  const result = probeMethods(schemaText, ['team/list', 'team/groups', 'team/install', 'team/set_active'])
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function TeamManager(props: {
  groups: readonly { id: string; name: string }[]
  onInstall: (id: string) => void
  onActivate: (id: string) => void
}): ReactElement {
  return createElement(
    'section',
    { 'data-testid': 'team-manager' },
    props.groups.map((group) =>
      createElement(
        'div',
        { key: group.id, 'data-group': group.id },
        group.name,
        createElement('button', { type: 'button', onClick: () => props.onInstall(group.id) }, 'Install'),
        createElement('button', { type: 'button', onClick: () => props.onActivate(group.id) }, 'Set active')
      )
    )
  )
}
