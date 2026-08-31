import { createElement, useMemo, useState, type ReactElement } from 'react'
import { TeamDetailOverlay } from './TeamPicker.ts'
import { teamInitials, teamOneLiner, teamScopeTags, teamCategory } from './team.model.ts'
import { memberPortraitSrc, teamPortraitSrc } from './team.portraits.ts'
import { gx28VisualState, type TeamGroup, type TeamRecord } from './team.visual.ts'

function Avatar(props: { src: string | null; name: string; large?: boolean }): ReactElement {
  const className = 'team-gallery-avatar' + (props.large === true ? ' team-gallery-avatar-lg' : '')
  if (props.src != null) {
    return createElement('img', {
      className,
      src: props.src,
      alt: '',
      'aria-hidden': 'true'
    })
  }
  return createElement('span', { className, 'aria-hidden': 'true' }, teamInitials(props.name))
}

export function TeamGallery(props: {
  groups: readonly TeamGroup[]
  teams: readonly TeamRecord[]
  loading?: boolean
  error?: string | null
  activeTeamId?: string | null
  labels?: {
    search?: string
    featured?: string
    specialists?: string
    all?: string
    use?: string
    intro?: string
    scope?: string
    ability?: string
    domains?: string
    members?: string
    leader?: string
    tryAsk?: string
    summonNamed?: string
  }
  onUse: (teamId: string) => void
}): ReactElement {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [openId, setOpenId] = useState<string | null>(null)
  const visual = gx28VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.teams.length === 0,
    narrow: false,
    dark: true
  })
  const labels = {
    search: props.labels?.search ?? '搜索专家团或描述',
    featured: props.labels?.featured ?? '精选场景',
    specialists: props.labels?.specialists ?? '专家团',
    all: props.labels?.all ?? '全部',
    use: props.labels?.use ?? '召唤',
    intro: props.labels?.intro ?? '部分简介',
    scope: props.labels?.scope ?? '应用范围',
    ability: props.labels?.ability ?? '能力介绍',
    domains: props.labels?.domains ?? '擅长领域',
    members: props.labels?.members ?? '团队成员',
    leader: props.labels?.leader ?? '主理人',
    tryAsk: props.labels?.tryAsk ?? '试试这样问我',
    summonNamed: props.labels?.summonNamed ?? '召唤 {name}'
  }
  const categories = useMemo(() => {
    const names = new Set<string>()
    for (const team of props.teams) names.add(teamCategory(team))
    return [...names]
  }, [props.teams])
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return props.teams.filter((team) => {
      const matchesQuery =
        needle === '' ||
        `${team.name} ${team.description ?? ''} ${team.summary ?? ''}`.toLowerCase().includes(needle)
      const matchesCategory = category === 'all' || teamCategory(team) === category
      return matchesQuery && matchesCategory
    })
  }, [category, props.teams, query])
  const featured = useMemo(
    () =>
      props.groups
        .map((group) => ({
          group,
          teams: filtered.filter((team) => team.groupId === group.id).slice(0, 4)
        }))
        .filter((entry) => entry.teams.length > 0),
    [filtered, props.groups]
  )
  const openTeam = props.teams.find((team) => team.id === openId) ?? null

  return createElement(
    'section',
    {
      className: 'team-gallery',
      'data-testid': 'team-gallery',
      'data-visual-state': visual
    },
    createElement(
      'header',
      { className: 'team-gallery-toolbar' },
      createElement('input', {
        type: 'search',
        className: 'team-gallery-search',
        'data-testid': 'team-gallery-search',
        placeholder: labels.search,
        value: query,
        onChange: (event: { target: { value: string } }) => setQuery(event.target.value)
      })
    ),
    featured.length > 0
      ? createElement(
          'div',
          { className: 'team-gallery-featured', 'data-testid': 'team-gallery-featured' },
          createElement('h3', { className: 'team-gallery-heading' }, labels.featured),
          createElement(
            'div',
            { className: 'team-gallery-featured-grid' },
            ...featured.map((entry) =>
              createElement(
                'article',
                { key: entry.group.id, className: 'team-gallery-scene', 'data-group': entry.group.id },
                createElement('h4', null, entry.group.name),
                createElement(
                  'ul',
                  null,
                  ...entry.teams.map((team) =>
                    createElement(
                      'li',
                      { key: team.id },
                      createElement(Avatar, { src: teamPortraitSrc(team.id), name: team.name }),
                      createElement('span', null, team.name)
                    )
                  )
                )
              )
            )
          )
        )
      : null,
    createElement('h3', { className: 'team-gallery-heading' }, labels.specialists),
    createElement(
      'div',
      { className: 'team-gallery-chips', 'data-testid': 'team-gallery-chips' },
      createElement(
        'button',
        {
          type: 'button',
          className: 'team-gallery-chip' + (category === 'all' ? ' is-active' : ''),
          onClick: () => setCategory('all')
        },
        labels.all
      ),
      ...categories.map((name) =>
        createElement(
          'button',
          {
            key: name,
            type: 'button',
            className: 'team-gallery-chip' + (category === name ? ' is-active' : ''),
            onClick: () => setCategory(name)
          },
          name
        )
      )
    ),
    visual === 'empty' ? createElement('p', { 'data-testid': 'team-gallery-empty' }, '还没有专家团。') : null,
    createElement(
      'div',
      { className: 'team-gallery-grid' },
      ...filtered.map((team) => {
        const line = teamOneLiner(team)
        const scope = teamScopeTags(team)
        return createElement(
          'article',
          {
            key: team.id,
            className: 'team-gallery-card' + (props.activeTeamId === team.id ? ' is-active' : ''),
            'data-testid': `team-gallery-card-${team.id}`,
            onClick: () => setOpenId(team.id)
          },
          createElement(
            'div',
            { className: 'team-gallery-card-head' },
            createElement(Avatar, { src: teamPortraitSrc(team.id), name: team.name, large: true }),
            createElement(
              'div',
              { className: 'team-gallery-card-copy' },
              createElement('h4', { className: 'team-gallery-card-title' }, team.name),
              line !== ''
                ? createElement('p', { className: 'team-gallery-card-body', 'data-testid': `team-card-intro-${team.id}` }, line)
                : null
            ),
            createElement(
              'button',
              {
                type: 'button',
                className: 'team-gallery-use',
                'data-testid': `use-team-${team.id}`,
                onClick: (event: { stopPropagation(): void }) => {
                  event.stopPropagation()
                  props.onUse(team.id)
                }
              },
              labels.use
            )
          ),
          scope.length > 0
            ? createElement(
                'div',
                { className: 'team-gallery-tags', 'data-testid': `team-card-scope-${team.id}` },
                ...scope.map((tag) => createElement('span', { key: tag, className: 'team-gallery-tag' }, tag))
              )
            : null
        )
      })
    ),
    openTeam != null
      ? createElement(TeamDetailOverlay, {
          team: openTeam,
          labels: {
            ability: labels.ability,
            domains: labels.domains,
            members: labels.members,
            leader: labels.leader,
            tryAsk: labels.tryAsk,
            summon: labels.summonNamed.replace('{name}', openTeam.name)
          },
          onSummon: () => {
            props.onUse(openTeam.id)
            setOpenId(null)
          },
          onClose: () => setOpenId(null)
        })
      : null
  )
}
