import { createElement, useState, type ReactElement } from 'react'
import { gx28VisualState, type TeamGroup, type TeamRecord } from './team.visual.ts'

export type TeamPickerView = 'groups' | 'teams' | 'detail'

export function TeamDetailCard(props: { team: TeamRecord }): ReactElement {
  const members = props.team.members ?? []
  const stages = props.team.stages ?? []
  const prompts = props.team.examplePrompts ?? []
  return createElement(
    'article',
    { 'data-testid': 'team-detail' },
    createElement('h3', null, props.team.name),
    props.team.description != null && props.team.description !== ''
      ? createElement('p', { 'data-testid': 'team-detail-description' }, props.team.description)
      : null,
    props.team.summary != null && props.team.summary !== ''
      ? createElement('p', { 'data-testid': 'team-detail-summary' }, props.team.summary)
      : null,
    members.length > 0
      ? createElement(
          'ol',
          { 'data-testid': 'team-detail-members' },
          members.map((member) =>
            createElement(
              'li',
              {
                key: member.role,
                'data-role': member.role,
                'data-leader': member.isLeader ? 'true' : 'false'
              },
              member.isLeader ? `${member.displayName}（主理人）` : member.displayName
            )
          )
        )
      : null,
    stages.length > 0
      ? createElement(
          'ol',
          { 'data-testid': 'team-detail-stages' },
          stages.map((stage) => createElement('li', { key: stage.name }, `${stage.name} · ${stage.role}`))
        )
      : null,
    prompts.length > 0
      ? createElement(
          'ul',
          { 'data-testid': 'team-detail-examples' },
          prompts.map((prompt) => createElement('li', { key: prompt }, prompt))
        )
      : null,
    createElement('p', { 'data-testid': 'team-cost-hint' }, '预估 token 倍数 3–5x')
  )
}

export function TeamPicker(props: {
  groups: readonly TeamGroup[]
  teams: readonly TeamRecord[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  onUse: (teamId: string) => void
}): ReactElement {
  const [view, setView] = useState<TeamPickerView>('groups')
  const [groupId, setGroupId] = useState<string | null>(null)
  const [teamId, setTeamId] = useState<string | null>(null)
  const visual = gx28VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.groups.length === 0,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  const inGroup = props.teams.filter((team) => team.groupId === groupId)
  const detail = props.teams.find((team) => team.id === teamId) ?? null
  return createElement(
    'div',
    {
      className: 'team-picker',
      'data-testid': 'team-picker',
      'data-view': view,
      'data-visual-state': visual
    },
    visual === 'loading' ? createElement('p', { 'data-testid': 'team-loading' }, 'Loading') : null,
    visual === 'error' ? createElement('p', { role: 'alert' }, props.error) : null,
    visual === 'empty' ? createElement('p', { 'data-testid': 'team-empty' }, 'No teams') : null,
    view === 'groups'
      ? createElement(
          'ul',
          { 'data-testid': 'team-group-list' },
          props.groups.map((group) =>
            createElement(
              'li',
              { key: group.id },
              createElement(
                'button',
                {
                  type: 'button',
                  onClick: () => {
                    setGroupId(group.id)
                    setView('teams')
                  }
                },
                group.name
              )
            )
          )
        )
      : null,
    view === 'teams'
      ? createElement(
          'ul',
          { 'data-testid': 'team-list' },
          inGroup.map((team) =>
            createElement(
              'li',
              { key: team.id },
              createElement(
                'button',
                {
                  type: 'button',
                  onClick: () => {
                    setTeamId(team.id)
                    setView('detail')
                  }
                },
                team.name
              )
            )
          )
        )
      : null,
    view === 'detail' && detail
      ? createElement(
          'div',
          null,
          createElement(TeamDetailCard, { team: detail }),
          createElement('button', { type: 'button', onClick: () => props.onUse(detail.id) }, 'Use team')
        )
      : null
  )
}
