import { createElement, type ReactElement } from 'react'
import { probeMethods } from '../gx/schemaProbe.ts'
import { gx28VisualState, type TeamGroup } from './team.visual.ts'

export function probeTeam(schemaText: string) {
  const result = probeMethods(schemaText, [
    'team/list',
    'team/groups',
    'team/install',
    'team/set_active',
    'team/group_rename'
  ])
  const required = ['team/list', 'team/groups', 'team/install', 'team/set_active']
  const missingRequired = required.filter((name) => result.missing.includes(name))
  return {
    path: missingRequired.length === 0 ? 'A' : 'B',
    present: result.present,
    missing: missingRequired
  }
}

export function TeamManager(props: {
  groups: readonly TeamGroup[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
  onInstall: (id: string) => void
  onActivate: (id: string) => void
}): ReactElement {
  const visual = gx28VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.groups.length === 0,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  return createElement(
    'section',
    {
      'data-testid': 'team-manager',
      'data-visual-state': visual
    },
    visual === 'empty' ? createElement('p', { 'data-testid': 'team-manager-empty' }, 'No groups') : null,
    ...props.groups.map((group) =>
      createElement(
        'div',
        { key: group.id, 'data-group': group.id, 'data-builtin': group.builtin ? 'true' : 'false' },
        group.name,
        createElement(
          'button',
          {
            type: 'button',
            disabled: group.builtin === true,
            onClick: () => props.onRename(group.id, `${group.name}-renamed`)
          },
          'Rename'
        ),
        createElement(
          'button',
          {
            type: 'button',
            disabled: group.builtin === true,
            onClick: () => props.onDelete(group.id)
          },
          'Delete'
        ),
        createElement('button', { type: 'button', onClick: () => props.onInstall(group.id) }, 'Install'),
        createElement('button', { type: 'button', onClick: () => props.onActivate(group.id) }, 'Set active')
      )
    )
  )
}
