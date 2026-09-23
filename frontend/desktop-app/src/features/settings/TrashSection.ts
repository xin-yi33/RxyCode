import { createElement, useMemo, useState, type ReactElement } from 'react'
import { normalizeLocale, t } from '../../i18n/t.ts'
import { ThemeMenu } from '../composer/ThemeMenu.ts'
import { PurgeConfirmDialog } from '../../components/PurgeConfirmDialog.ts'
import { TrashItem, type TrashItemModel } from '../../components/TrashItem.ts'
import {
  filterArchived,
  groupArchivedByProject,
  gx21VisualState
} from '../recycle/recycle.probe.ts'

export function TrashSection(props: {
  items: readonly TrashItemModel[]
  blocked: boolean
  missing: readonly string[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
  backendError?: string | null
  locale?: string
  onRestore: (id: string) => void
  onPurgeConfirmed: () => void
  onPurgeItem?: (id: string) => void
}): ReactElement {
  const locale = normalizeLocale(props.locale)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [chatFilter, setChatFilter] = useState('all')
  const [projectKey, setProjectKey] = useState('all')
  const visual = gx21VisualState({
    loading: props.loading === true,
    error: props.error ?? null,
    empty: props.items.length === 0,
    narrow: props.narrow === true,
    dark: props.dark === true
  })
  const filtered = useMemo(
    () => filterArchived(props.items, query, projectKey),
    [props.items, query, projectKey]
  )
  const groups = useMemo(() => groupArchivedByProject(filtered), [filtered])
  const projectOptions = useMemo(() => {
    const keys = new Map<string, string>()
    for (const group of groupArchivedByProject(props.items)) {
      keys.set(group.projectKey, group.projectKey === '__none__' ? t(locale, 'recent') : group.displayName)
    }
    return [...keys.entries()]
  }, [locale, props.items])

  return createElement(
    'section',
    {
      className: 'trash-section archived-chats',
      'data-testid': 'trash-section',
      'data-visual-state': visual,
      'data-blocked': props.blocked ? 'true' : 'false'
    },
    createElement(
      'header',
      { className: 'archived-header' },
      createElement('h2', { className: 'archived-title' }, t(locale, 'recycle')),
      createElement(
        'button',
        {
          type: 'button',
          className: 'archived-delete-all',
          'data-action': 'open-purge',
          disabled: props.blocked || props.items.length === 0,
          onClick: () => setConfirmOpen(true)
        },
        t(locale, 'deleteAllArchived')
      )
    ),
    createElement(
      'div',
      { className: 'archived-toolbar' },
      createElement('input', {
        type: 'search',
        className: 'archived-search',
        'data-testid': 'archived-search',
        placeholder: t(locale, 'searchArchived'),
        value: query,
        onChange: (event: { target: { value: string } }) => setQuery(event.target.value)
      }),
      createElement(ThemeMenu, {
        value: chatFilter,
        options: [{ value: 'all', label: t(locale, 'allChats') }],
        onChange: setChatFilter,
        testId: 'archived-chat-filter',
        ariaLabel: t(locale, 'allChats'),
        placement: 'down',
        align: 'end'
      }),
      createElement(ThemeMenu, {
        value: projectKey,
        options: [
          { value: 'all', label: t(locale, 'allProjects') },
          ...projectOptions.map(([key, label]) => ({ value: key, label }))
        ],
        onChange: setProjectKey,
        testId: 'archived-project-filter',
        ariaLabel: t(locale, 'allProjects'),
        placement: 'down',
        align: 'end'
      })
    ),
    props.blocked
      ? createElement(
          'p',
          { 'data-testid': 'recycle-blocked' },
          `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}`
        )
      : null,
    visual === 'loading' ? createElement('p', { 'data-testid': 'trash-loading' }, t(locale, 'loading')) : null,
    visual === 'error' ? createElement('p', { role: 'alert' }, props.error) : null,
    visual === 'empty' ? createElement('p', { 'data-testid': 'trash-empty' }, t(locale, 'noArchivedChats')) : null,
    ...groups.map((group) =>
      createElement(
        'section',
        { key: group.projectKey, className: 'archived-group' },
        createElement(
          'div',
          { className: 'archived-group-head' },
          createElement(
            'p',
            { className: 'archived-group-title' },
            group.projectKey === '__none__' ? t(locale, 'recent') : group.displayName
          ),
          createElement(
            'span',
            { className: 'archived-group-count' },
            t(locale, 'archivedCount', { count: String(group.items.length) })
          )
        ),
        ...group.items.map((item) =>
          createElement(TrashItem, {
            key: item.id,
            item,
            locale: props.locale,
            unarchiveLabel: t(locale, 'unarchiveChat'),
            onRestore: props.onRestore,
            onPurge: props.onPurgeItem
          })
        )
      )
    ),
    createElement(PurgeConfirmDialog, {
      open: confirmOpen,
      backendError: props.backendError ?? null,
      onCancel: () => setConfirmOpen(false),
      onConfirm: () => {
        setConfirmOpen(false)
        props.onPurgeConfirmed()
      }
    })
  )
}
