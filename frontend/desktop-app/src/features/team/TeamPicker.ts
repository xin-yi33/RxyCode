import { createElement, useState, type ReactElement } from 'react'
import { teamCategory, teamInitials, teamScopeTags } from './team.model.ts'
import { memberPortraitSrc, teamPortraitSrc } from './team.portraits.ts'
import { gx28VisualState, type TeamGroup, type TeamRecord } from './team.visual.ts'

export type TeamPickerView = 'groups' | 'teams' | 'detail'

function Portrait(props: { src: string | null; name: string; className: string }): ReactElement {
  if (props.src != null) {
    return createElement('img', { className: props.className, src: props.src, alt: '' })
  }
  return createElement('span', { className: props.className, 'aria-hidden': 'true' }, teamInitials(props.name))
}

export function TeamDetailCard(props: {
  team: TeamRecord
  labels?: {
    ability?: string
    domains?: string
    members?: string
    leader?: string
    tryAsk?: string
    summon?: string
  }
  onSummon?: () => void
}): ReactElement {
  const members = props.team.members ?? []
  const stages = props.team.stages ?? []
  const prompts = props.team.examplePrompts ?? []
  const labels = {
    ability: props.labels?.ability ?? '能力介绍',
    domains: props.labels?.domains ?? '擅长领域',
    members: props.labels?.members ?? '团队成员',
    leader: props.labels?.leader ?? '主理人',
    tryAsk: props.labels?.tryAsk ?? '试试这样问我',
    summon: props.labels?.summon ?? `召唤 ${props.team.name}`
  }
  const scope = teamScopeTags(props.team)
  const category = teamCategory(props.team)
  return createElement(
    'article',
    { className: 'team-detail-card', 'data-testid': 'team-detail' },
    createElement(
      'header',
      { className: 'team-detail-head' },
      createElement(Portrait, {
        src: teamPortraitSrc(props.team.id),
        name: props.team.name,
        className: 'team-detail-cover'
      }),
      createElement(
        'div',
        { className: 'team-detail-titles' },
        createElement('h3', null, props.team.name),
        category !== '' ? createElement('p', { className: 'team-detail-category' }, category) : null
      )
    ),
    props.team.description != null && props.team.description !== ''
      ? createElement(
          'section',
          { className: 'team-detail-section' },
          createElement('h4', null, labels.ability),
          createElement('p', { 'data-testid': 'team-detail-description' }, props.team.description)
        )
      : null,
    props.team.summary != null && props.team.summary !== ''
      ? createElement('p', { 'data-testid': 'team-detail-summary' }, props.team.summary)
      : null,
    scope.length > 0
      ? createElement(
          'section',
          { className: 'team-detail-section' },
          createElement('h4', null, labels.domains),
          createElement(
            'div',
            { className: 'team-detail-tags', 'data-testid': 'team-detail-domains' },
            ...scope.map((tag) => createElement('span', { key: tag, className: 'team-gallery-tag' }, tag))
          )
        )
      : null,
    members.length > 0
      ? createElement(
          'section',
          { className: 'team-detail-section' },
          createElement('h4', null, labels.members),
          createElement(
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
                createElement(Portrait, {
                  src: memberPortraitSrc(member.role),
                  name: member.displayName,
                  className: 'team-member-avatar'
                }),
                createElement('span', null, member.displayName),
                member.isLeader
                  ? createElement('span', { className: 'team-leader-badge' }, labels.leader)
                  : null
              )
            )
          )
        )
      : null,
    props.onSummon == null && stages.length > 0
      ? createElement(
          'ol',
          { 'data-testid': 'team-detail-stages' },
          stages.map((stage) => createElement('li', { key: stage.name }, `${stage.name} · ${stage.role}`))
        )
      : null,
    prompts.length > 0
      ? createElement(
          'section',
          { className: 'team-detail-section' },
          createElement('h4', null, labels.tryAsk),
          createElement(
            'ul',
            { 'data-testid': 'team-detail-examples' },
            prompts.map((prompt) =>
              createElement('li', { key: prompt, className: 'team-detail-prompt' }, prompt)
            )
          )
        )
      : null,
    props.onSummon == null
      ? createElement('p', { 'data-testid': 'team-cost-hint' }, '预估 token 倍数 3–5x')
      : null,
    props.onSummon != null
      ? createElement(
          'button',
          {
            type: 'button',
            className: 'team-detail-summon',
            'data-testid': 'team-detail-summon',
            onClick: props.onSummon
          },
          labels.summon
        )
      : null
  )
}

export function TeamDetailOverlay(props: {
  team: TeamRecord
  labels?: {
    ability?: string
    domains?: string
    members?: string
    leader?: string
    tryAsk?: string
    summon?: string
  }
  onSummon: () => void
  onClose: () => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'team-detail-overlay', 'data-testid': 'team-detail-overlay', role: 'dialog' },
    createElement('button', {
      type: 'button',
      className: 'team-detail-backdrop',
      'aria-label': 'close',
      onClick: props.onClose
    }),
    createElement(
      'div',
      { className: 'team-detail-dialog' },
      createElement(
        'button',
        { type: 'button', className: 'team-detail-close', 'data-testid': 'team-detail-close', onClick: props.onClose },
        '×'
      ),
      createElement(TeamDetailCard, { team: props.team, labels: props.labels, onSummon: props.onSummon })
    )
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
