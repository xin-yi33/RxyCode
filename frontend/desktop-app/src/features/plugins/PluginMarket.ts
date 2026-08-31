import { createElement, useEffect, useMemo, useState, type ReactElement } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { TeamGallery } from '../team/TeamGallery.ts'
import type { TeamGroup, TeamRecord } from '../team/team.visual.ts'
import { GITHUB_PLUGIN } from './plugin.model.ts'
import { pluginPortraitSrc, skillPortraitSrc, type SkillMarketItem } from '../skills/skill.model.ts'
import { usePlugins } from '../../renderer/src/hooks/usePlugins.ts'
import { useSkillMarket } from '../../renderer/src/hooks/useSkillMarket.ts'

export type PluginHubTab = 'plugins' | 'skills' | 'teams'
export type SkillPane = 'market' | 'installed'
export type SkillFilter = 'hot' | 'hub' | 'add'

export function PluginMarket(props: {
  blocked: boolean
  missing: readonly string[]
  client?: ProtocolClient | null
  teams?: readonly TeamRecord[]
  groups?: readonly TeamGroup[]
  teamLoading?: boolean
  teamError?: string | null
  onSummonTeam?: (teamId: string) => void
  onCreateSkill?: (need: string) => void
}): ReactElement {
  const [tab, setTab] = useState<PluginHubTab>('plugins')
  if (props.blocked) {
    return createElement(
      'section',
      { 'data-testid': 'plugin-market', 'data-blocked': 'true' },
      `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}`
    )
  }
  return createElement(
    'section',
    { className: 'plugin-hub', 'data-testid': 'plugin-market', 'data-blocked': 'false' },
    createElement(
      'nav',
      { className: 'plugin-hub-nav', 'data-testid': 'plugin-hub-nav' },
      ([['plugins', '插件'], ['skills', '技能'], ['teams', '专家团']] as const).map(([id, label]) =>
        createElement(
          'button',
          {
            key: id,
            type: 'button',
            className: 'plugin-hub-tab' + (tab === id ? ' is-active' : ''),
            'data-testid': `plugin-hub-${id}`,
            onClick: () => setTab(id)
          },
          label
        )
      )
    ),
    tab === 'plugins'
      ? createElement(PluginPane, { client: props.client ?? null })
      : null,
    tab === 'skills'
      ? createElement(SkillPaneView, { client: props.client ?? null, onCreateSkill: props.onCreateSkill })
      : null,
    tab === 'teams'
      ? createElement(TeamGallery, {
          groups: props.groups ?? [],
          teams: props.teams ?? [],
          loading: props.teamLoading,
          error: props.teamError,
          labels: { use: '召唤', intro: '部分简介', scope: '应用范围' },
          onUse: (teamId) => props.onSummonTeam?.(teamId)
        })
      : null
  )
}

function PluginPane(props: { client: ProtocolClient | null }): ReactElement {
  const plugins = usePlugins(props.client)
  const [query, setQuery] = useState('')
  const [githubUrl, setGithubUrl] = useState('')
  const [notice, setNotice] = useState('')
  const installed = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return plugins.items.filter((item) => needle === '' || `${item.name} ${item.description}`.toLowerCase().includes(needle))
  }, [plugins.items, query])
  const githubInstalled = plugins.items.some((item) => item.name.toLowerCase() === 'github')

  return createElement(
    'div',
    { className: 'plugin-pane', 'data-testid': 'plugin-pane' },
    createElement('h3', { className: 'plugin-pane-title' }, '插件'),
    createElement('p', { className: 'plugin-pane-sub' }, '在常用工具里接上 RxyCode'),
    createElement('input', {
      className: 'plugin-search',
      'data-testid': 'plugin-search',
      placeholder: '搜索插件',
      value: query,
      onChange: (event: { target: { value: string } }) => setQuery(event.target.value)
    }),
    createElement('h4', null, '已安装'),
    createElement(
      'div',
      { className: 'plugin-installed-icons', 'data-testid': 'plugin-installed' },
      installed.length === 0
        ? createElement('p', { className: 'plugin-empty' }, plugins.error ?? '还没有安装插件。')
        : installed.map((item) =>
            createElement(
              'button',
              {
                key: item.name,
                type: 'button',
                className: 'plugin-icon-tile',
                title: item.name,
                onClick: () => void plugins.toggle(item.name, !item.enabled)
              },
              createElement('img', { src: pluginPortraitSrc(item.name), alt: '' }),
              createElement('span', null, item.name)
            )
          )
    ),
    createElement('h4', null, 'Popular'),
    createElement(
      'article',
      { className: 'plugin-row', 'data-testid': 'plugin-github' },
      createElement('img', { className: 'plugin-row-icon', src: pluginPortraitSrc('github'), alt: '' }),
      createElement(
        'div',
        { className: 'plugin-row-copy' },
        createElement('strong', null, GITHUB_PLUGIN.title),
        createElement('p', null, GITHUB_PLUGIN.description)
      ),
      githubInstalled
        ? createElement('span', { className: 'plugin-installed-badge' }, '已连接')
        : createElement(
            'div',
            { className: 'plugin-github-form' },
            createElement('input', {
              'data-testid': 'plugin-github-url',
              placeholder: 'https://github.com/org/plugin/archive/refs/heads/main.zip',
              value: githubUrl,
              onChange: (event: { target: { value: string } }) => setGithubUrl(event.target.value)
            }),
            createElement(
              'button',
              {
                type: 'button',
                'data-testid': 'plugin-github-connect',
                disabled: githubUrl.trim() === '',
                onClick: () => {
                  void plugins.install({ source: 'github', path: githubUrl.trim(), name: 'github' }).then(setNotice)
                }
              },
              '连接'
            )
          )
    ),
    notice !== '' ? createElement('p', { role: 'alert', 'data-testid': 'plugin-notice' }, notice) : null,
    plugins.error != null ? createElement('p', { role: 'alert' }, plugins.error) : null
  )
}

function SkillPaneView(props: {
  client: ProtocolClient | null
  onCreateSkill?: (need: string) => void
}): ReactElement {
  const skills = useSkillMarket(props.client)
  const [pane, setPane] = useState<SkillPane>('market')
  const [filter, setFilter] = useState<SkillFilter>('hot')
  const [query, setQuery] = useState('')
  const [openName, setOpenName] = useState<string | null>(null)
  const [localPath, setLocalPath] = useState('')
  const [localName, setLocalName] = useState('')
  const [llmNeed, setLlmNeed] = useState('')
  const [notice, setNotice] = useState('')
  const installedCount = skills.installed.filter((item) => item.installed).length

  useEffect(() => {
    void skills.search('SKILL', 'github')
    void skills.search('', 'hub')
  }, [skills.search])

  const marketRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const rows = filter === 'hub' ? skills.hub : skills.market
    return rows
      .filter((item) => needle === '' || `${item.name} ${item.description} ${item.scope}`.toLowerCase().includes(needle))
      .slice()
      .sort((a, b) => b.stars - a.stars)
  }, [filter, query, skills.hub, skills.market])
  const installedRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return skills.installed.filter(
      (item) => needle === '' || `${item.name} ${item.description} ${item.scope}`.toLowerCase().includes(needle)
    )
  }, [query, skills.installed])
  const openItem =
    [...skills.installed, ...skills.market, ...skills.hub].find((item) => item.name === openName) ?? null

  return createElement(
    'div',
    { className: 'skill-pane', 'data-testid': 'skill-pane' },
    createElement(
      'header',
      { className: 'skill-pane-toolbar' },
      createElement('input', {
        className: 'plugin-search',
        'data-testid': 'skill-search',
        placeholder: '搜索技能',
        value: query,
        onChange: (event: { target: { value: string } }) => setQuery(event.target.value)
      })
    ),
    createElement(
      'div',
      { className: 'skill-subnav' },
      createElement(
        'button',
        {
          type: 'button',
          className: pane === 'market' ? 'is-active' : '',
          'data-testid': 'skill-tab-market',
          onClick: () => setPane('market')
        },
        '技能市场'
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: pane === 'installed' ? 'is-active' : '',
          'data-testid': 'skill-tab-installed',
          onClick: () => setPane('installed')
        },
        `已安装 ${installedCount}`
      )
    ),
    createElement(
      'div',
      { className: 'skill-filters' },
      createElement(
        'button',
        {
          type: 'button',
          className: filter === 'hot' ? 'is-active' : '',
          'data-testid': 'skill-filter-hot',
          onClick: () => {
            setFilter('hot')
            setPane('market')
          }
        },
        '热门'
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: filter === 'hub' ? 'is-active' : '',
          'data-testid': 'skill-filter-hub',
          onClick: () => {
            setFilter('hub')
            setPane('market')
          }
        },
        'SkillHub'
      ),
      createElement(
        'button',
        {
          type: 'button',
          className: filter === 'add' ? 'is-active' : '',
          'data-testid': 'skill-filter-add',
          onClick: () => setFilter('add')
        },
        '添加'
      )
    ),
    filter === 'add'
      ? createElement(
          'div',
          { className: 'skill-add', 'data-testid': 'skill-add' },
          createElement('p', { className: 'plugin-pane-sub' }, '从本地 SKILL.md / zip 安装，或让对话去 GitHub 搜索安装。'),
          createElement('input', {
            'data-testid': 'skill-local-name',
            placeholder: '技能名',
            value: localName,
            onChange: (event: { target: { value: string } }) => setLocalName(event.target.value)
          }),
          createElement('input', {
            'data-testid': 'skill-local-path',
            placeholder: '本地路径或 https://.../SKILL.md',
            value: localPath,
            onChange: (event: { target: { value: string } }) => setLocalPath(event.target.value)
          }),
          createElement(
            'button',
            {
              type: 'button',
              'data-testid': 'skill-local-install',
              disabled: localPath.trim() === '' || localName.trim() === '',
              onClick: () => {
                const path = localPath.trim()
                const source = path.startsWith('http') ? 'url' : 'local'
                void skills
                  .install({
                    source,
                    path,
                    url: path,
                    name: localName.trim()
                  })
                  .then(setNotice)
              }
            },
            '安装文件'
          ),
          createElement('textarea', {
            'data-testid': 'skill-llm-need',
            placeholder: '描述你需要的 skill，将用提示词让对话去搜索并安装',
            value: llmNeed,
            onChange: (event: { target: { value: string } }) => setLlmNeed(event.target.value)
          }),
          createElement(
            'button',
            {
              type: 'button',
              'data-testid': 'skill-llm-create',
              disabled: llmNeed.trim() === '',
              onClick: () => props.onCreateSkill?.(llmNeed.trim())
            },
            '用对话搜索安装'
          )
        )
      : createElement(
          'div',
          { className: 'skill-grid', 'data-testid': pane === 'installed' ? 'skill-installed-grid' : 'skill-market-grid' },
          (pane === 'installed' ? installedRows : marketRows).map((item) =>
            createElement(SkillCard, {
              key: `${item.source}-${item.name}`,
              item,
              onOpen: () => {
                setOpenName(item.name)
                void skills.loadDetail(`skill:${item.name}`)
              },
              onAdd: () => {
                void skills
                  .install({
                    source: item.repo ? 'github' : 'query',
                    query: item.name,
                    name: item.name
                  })
                  .then(setNotice)
              }
            })
          )
        ),
    skills.error != null ? createElement('p', { role: 'alert' }, skills.error) : null,
    notice !== '' ? createElement('p', { role: 'alert' }, notice) : null,
    openItem != null
      ? createElement(SkillDetailOverlay, {
          item: openItem,
          body: skills.detail,
          onClose: () => setOpenName(null),
          onInstall: () => {
            void skills.install({ source: 'github', query: openItem.name, name: openItem.name }).then(setNotice)
          }
        })
      : null
  )
}

function SkillCard(props: {
  item: SkillMarketItem
  onOpen: () => void
  onAdd: () => void
}): ReactElement {
  return createElement(
    'article',
    {
      className: 'skill-card',
      'data-testid': `skill-card-${props.item.name}`,
      onClick: props.onOpen
    },
    createElement('img', { className: 'skill-card-icon', src: skillPortraitSrc(props.item.name), alt: '' }),
    createElement(
      'div',
      { className: 'skill-card-copy' },
      createElement('strong', null, props.item.name),
      props.item.description !== ''
        ? createElement('p', { className: 'skill-card-intro' }, createElement('span', null, '简介'), props.item.description)
        : null,
      props.item.scope !== ''
        ? createElement('p', { className: 'skill-card-scope' }, createElement('span', null, '适用范围'), props.item.scope)
        : null,
      props.item.stars > 0 ? createElement('small', null, `${props.item.stars} stars`) : null
    ),
    createElement(
      'button',
      {
        type: 'button',
        className: 'skill-card-add',
        'data-testid': `skill-add-${props.item.name}`,
        onClick: (event: { stopPropagation(): void }) => {
          event.stopPropagation()
          props.onAdd()
        }
      },
      props.item.installed ? '✓' : '+'
    )
  )
}

function SkillDetailOverlay(props: {
  item: SkillMarketItem
  body: string
  onClose: () => void
  onInstall: () => void
}): ReactElement {
  return createElement(
    'div',
    { className: 'team-detail-overlay', 'data-testid': 'skill-detail-overlay', role: 'dialog' },
    createElement('button', {
      type: 'button',
      className: 'team-detail-backdrop',
      'aria-label': 'close',
      onClick: props.onClose
    }),
    createElement(
      'div',
      { className: 'team-detail-dialog skill-detail-dialog' },
      createElement('button', { type: 'button', className: 'team-detail-close', onClick: props.onClose }, '×'),
      createElement(
        'header',
        { className: 'skill-detail-head' },
        createElement('img', { src: skillPortraitSrc(props.item.name), alt: '' }),
        createElement(
          'div',
          null,
          createElement('h3', null, props.item.name),
          props.item.description !== '' ? createElement('p', null, props.item.description) : null
        )
      ),
      createElement('h4', null, '使用说明'),
      createElement('pre', { className: 'skill-detail-body', 'data-testid': 'skill-detail-body' }, props.body || props.item.description),
      createElement('h4', null, '适用范围'),
      createElement('p', { 'data-testid': 'skill-detail-scope' }, props.item.scope || props.item.repo || '—'),
      createElement(
        'button',
        { type: 'button', className: 'team-detail-summon', onClick: props.onInstall },
        props.item.installed ? '已安装' : '安装'
      )
    )
  )
}
