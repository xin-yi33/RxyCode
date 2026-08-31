import { Archive, Clock, Folder, MoreHorizontal, Pencil, Pin, Plus, Puzzle, Search, Settings } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import {
  CHEVRON_GAP_PX,
  chevron,
  HOVER_DARK,
  HOVER_LIGHT,
  projectCategories,
  type CategorizedSession
} from '../../../lib/sessionCategories.ts'
import type { RunState, SessionEntry } from '../lib/conversationStore.mts'
import { StatusIndicator } from '../../../components/StatusIndicator.tsx'
import { sessionRowChrome } from '../../../lib/statusProjection.ts'
import { SETTINGS_ENTRY } from '../../../lib/settingsSections.ts'
import {
  normalizeProjectCwd,
  sidebarProjects,
  type ProjectRecord
} from '../../../features/projects/projectRegistry.ts'
import { sessionVisualState } from './sessionVisualState.ts'

export const SESSION_FOLD_STORAGE_KEY = 'rxycode.desktop.sessionFold.v1'

interface SessionListProps {
  sessions: SessionEntry[]
  activeSessionId: string | null
  runStateBySession?: Record<string, RunState>
  childCountBySession?: Record<string, number>
  disabled: boolean
  loading?: boolean
  error?: string | null
  listDeletedAvailable?: boolean
  pinnedIds?: readonly string[]
  runningBySession?: Record<string, boolean>
  unreadIds?: readonly string[]
  projects?: readonly ProjectRecord[]
  onCreate: () => void
  onSelect: (sessionId: string) => void
  onRename?: (sessionId: string, title: string) => void
  onTrash?: (sessionId: string) => void
  onRestore?: (sessionId: string) => void
  onPurge?: (sessionId: string) => void
  onAddProject?: () => void
  onCreateInProject?: (cwd: string) => void
  onPin?: (sessionId: string, pinned: boolean) => void
  onOpenSettings?: () => void
  onOpenScheduled?: () => void
  onOpenPlugins?: () => void
}

interface FoldState {
  pinned: boolean
  projects: boolean
  recent: boolean
}

const DEFAULT_FOLD: FoldState = { pinned: true, projects: true, recent: true }

function loadFold(storage: Pick<Storage, 'getItem'> | undefined): FoldState {
  if (storage === undefined) return { ...DEFAULT_FOLD }
  try {
    const raw = storage.getItem(SESSION_FOLD_STORAGE_KEY)
    if (raw === null) return { ...DEFAULT_FOLD }
    const parsed = JSON.parse(raw) as Partial<FoldState>
    return {
      pinned: parsed.pinned !== false,
      projects: parsed.projects !== false,
      recent: parsed.recent !== false
    }
  } catch {
    return { ...DEFAULT_FOLD }
  }
}

function toCategorized(
  sessions: SessionEntry[],
  pinnedIds: readonly string[]
): CategorizedSession[] {
  const pinned = new Set(pinnedIds)
  return sessions.map((session) => ({
    sessionId: session.sessionId,
    title: session.title,
    workspaceRoot: session.workspaceRoot,
    pinned: session.pinned || pinned.has(session.sessionId),
    deletedAt: session.trashedAt === null ? null : String(session.trashedAt),
    projectId: session.workspaceRoot === '' ? null : session.workspaceRoot
  }))
}

function SessionList({
  sessions,
  activeSessionId,
  runStateBySession = {},
  childCountBySession = {},
  disabled,
  loading = false,
  error = null,
  listDeletedAvailable = false,
  pinnedIds = [],
  runningBySession = {},
  unreadIds = [],
  projects = [],
  onCreate,
  onSelect,
  onRename,
  onTrash,
  onAddProject,
  onCreateInProject,
  onPin,
  onOpenSettings,
  onOpenScheduled,
  onOpenPlugins
}: SessionListProps): React.JSX.Element {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [fold, setFold] = useState<FoldState>(() => loadFold(typeof window === 'undefined' ? undefined : window.localStorage))
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)
  const normalizedQuery = query.trim().toLowerCase()
  const matches = (session: SessionEntry): boolean =>
    normalizedQuery === '' || `${session.title} ${session.workspaceRoot}`.toLowerCase().includes(normalizedQuery)

  const visible = sessions.filter(matches)
  const buckets = useMemo(
    () => projectCategories(toCategorized(visible, pinnedIds), listDeletedAvailable),
    [visible, pinnedIds, listDeletedAvailable]
  )
  const sessionById = useMemo(
    () => new Map(sessions.map((session) => [session.sessionId, session])),
    [sessions]
  )
  const theme = typeof document === 'undefined' ? 'dark' : document.documentElement.dataset.theme
  const visual = sessionVisualState({
    loading,
    error,
    empty: sessions.length === 0,
    narrow: false,
    dark: theme !== 'light'
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(SESSION_FOLD_STORAGE_KEY, JSON.stringify(fold))
  }, [fold])

  useEffect(() => {
    if (renamingId !== null) renameInputRef.current?.focus()
  }, [renamingId])

  const requestRename = (session: SessionEntry): void => {
    if (onRename === undefined) return
    setRenamingId(session.sessionId)
    setRenameValue(session.title)
  }

  const submitRename = (sessionId: string): void => {
    const next = renameValue.trim()
    if (onRename !== undefined && next !== '') onRename(sessionId, next)
    setRenamingId(null)
    setRenameValue('')
  }

  const toggle = (key: keyof FoldState): void => {
    setFold((current) => ({ ...current, [key]: !current[key] }))
  }

  const renderTask = (session: SessionEntry, trashed: boolean): React.JSX.Element => {
    const state = runStateBySession[session.sessionId] ?? 'succeeded'
    const childCount = childCountBySession[session.sessionId] ?? 0
    const pinned = session.pinned || pinnedIds.includes(session.sessionId)
    const chrome = sessionRowChrome({
      runState: state,
      running: runningBySession[session.sessionId] === true,
      unread: unreadIds.includes(session.sessionId)
    })
    return (
      <li key={session.sessionId} className={'session-row' + (chrome === 'unread' ? ' has-unread' : '')}>
        {chrome === 'unread' ? (
          <span className="session-unread-dot" data-testid={`unread-task-${session.sessionId}`} aria-hidden="true" />
        ) : (
          <span className="session-unread-slot" aria-hidden="true" />
        )}
        <div className="session-row-main">
          {renamingId === session.sessionId && !trashed ? (
            <form
              className="session-rename-form"
              onSubmit={(event) => {
                event.preventDefault()
                submitRename(session.sessionId)
              }}
              onClick={(event) => event.stopPropagation()}
            >
              <input
                ref={renameInputRef}
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    event.preventDefault()
                    setRenamingId(null)
                    setRenameValue('')
                  }
                }}
                aria-label={`${t('rename')} ${session.title}`}
                data-testid={`rename-input-${session.sessionId}`}
              />
              <button type="submit" className="rename-save" data-testid={`rename-save-${session.sessionId}`}>{t('save')}</button>
              <button type="button" className="rename-cancel" data-testid={`rename-cancel-${session.sessionId}`} onClick={() => { setRenamingId(null); setRenameValue('') }}>{t('cancel')}</button>
            </form>
          ) : (
            <button
              type="button"
              className={`session-item${session.sessionId === activeSessionId ? ' active' : ''}${chrome === 'spin' ? ' is-running' : ''}`}
              onClick={() => onSelect(session.sessionId)}
              disabled={trashed}
              data-testid={`session-${session.sessionId}`}
              data-run-state={state}
              data-chrome={chrome}
            >
              <span className="session-title-row">
                <span className="session-title">{session.title}</span>
                {chrome === 'spin' ? <StatusIndicator backend="running" visualState={visual} /> : null}
              </span>
              {childCount > 0 && <span className="session-child-count">{childCount}</span>}
            </button>
          )}
        </div>
        {trashed ? null : (
          <div className="session-actions" aria-label={`${session.title} actions`}>
            {onPin !== undefined ? (
              <button
                type="button"
                className={'icon-button pin-button' + (pinned ? ' is-pinned' : '')}
                title={pinned ? t('unpinTask') : t('pinTask')}
                aria-label={pinned ? t('unpinTask') : t('pinTask')}
                aria-pressed={pinned}
                data-testid={`pin-task-${session.sessionId}`}
                onClick={() => onPin(session.sessionId, !pinned)}
              >
                <Pin aria-hidden="true" size={14} fill={pinned ? 'currentColor' : 'none'} strokeWidth={1.75} />
              </button>
            ) : null}
            <button type="button" className="icon-button" title={t('rename')} aria-label={t('rename')} data-testid={`rename-task-${session.sessionId}`} onClick={() => requestRename(session)}>
              <Pencil aria-hidden="true" size={14} />
            </button>
            <button type="button" className="icon-button" title={t('archiveChat')} aria-label={t('archiveChat')} data-testid={`trash-task-${session.sessionId}`} onClick={() => onTrash?.(session.sessionId)}>
              <Archive aria-hidden="true" size={14} />
            </button>
          </div>
        )}
      </li>
    )
  }

  const renderCategory = (
    id: keyof FoldState,
    title: string,
    items: SessionEntry[],
    extra?: React.JSX.Element
  ): React.JSX.Element => {
    const expanded = fold[id]
    return (
      <section className="session-category" data-testid={`session-category-${id}`}>
        <div className="session-category-head">
          <button
            type="button"
            className="session-category-title"
            aria-expanded={expanded}
            onClick={() => toggle(id)}
          >
            {title}
            <span className="session-category-chevron" style={{ marginLeft: CHEVRON_GAP_PX }}>
              {chevron(expanded)}
            </span>
          </button>
          {extra}
        </div>
        {expanded && items.length === 0 ? (
          <p className="empty-hint" data-testid={`session-category-${id}-empty`}>{t('emptyTasks')}</p>
        ) : null}
        {expanded && items.length > 0 ? (
          <ul className="session-list">{items.map((session) => renderTask(session, false))}</ul>
        ) : null}
      </section>
    )
  }

  const resolve = (entries: CategorizedSession[]): SessionEntry[] =>
    entries
      .map((entry) => sessionById.get(entry.sessionId))
      .filter((session): session is SessionEntry => session !== undefined)

  const sessionsForCwd = (cwd: string): SessionEntry[] => {
    const key = normalizeProjectCwd(cwd)
    for (const [projectId, entries] of Object.entries(buckets.projects)) {
      if (normalizeProjectCwd(projectId) === key) return resolve(entries)
    }
    return []
  }
  const projectRows = sidebarProjects(
    projects,
    Object.fromEntries(
      Object.entries(buckets.projects).map(([cwd, entries]) => [cwd, entries.map((entry) => entry.sessionId)])
    )
  )
  const projectSections = projectRows.map((row) => (
    <section key={row.cwd} className="session-project" data-testid={`session-project-${row.cwd}`}>
      <div className="session-project-head">
        <Folder className="session-project-folder" aria-hidden="true" size={14} />
        <p className="session-project-title" title={row.cwd}>{row.displayName}</p>
        {onCreateInProject !== undefined ? (
          <button
            type="button"
            className="session-head-action"
            data-testid={`new-in-project-${row.cwd}`}
            title={t('newInProject')}
            aria-label={t('newInProject')}
            onClick={() => onCreateInProject(row.cwd)}
            disabled={disabled}
          >
            <Plus aria-hidden="true" size={14} />
          </button>
        ) : null}
      </div>
      <ul className="session-list session-list-in-project">{sessionsForCwd(row.cwd).map((session) => renderTask(session, false))}</ul>
    </section>
  ))

  return (
    <aside
      className="session-panel"
      data-testid="session-nav"
      data-visual-state={visual}
      data-hover-light={HOVER_LIGHT}
      data-hover-dark={HOVER_DARK}
      aria-label={t('tasks')}
    >
      <div className="panel-header">
        <span className="panel-title">{t('tasks')}</span>
        <button type="button" className="new-session" onClick={onCreate} disabled={disabled} title={t('newTask')} aria-label={t('newTask')} data-testid="new-session">
          <Plus aria-hidden="true" size={16} />
        </button>
      </div>
      <label className="session-search">
        <Search aria-hidden="true" size={14} />
        <span className="sr-only">{t('searchTasks')}</span>
        <input type="search" placeholder={t('searchTasks')} aria-label={t('searchTasks')} value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <nav className="session-shortcuts" aria-label={t('tasks')}>
        <button type="button" className="session-shortcut" data-testid="sidebar-new" onClick={onCreate} disabled={disabled}>
          <Plus aria-hidden="true" size={14} />
          <span>{t('newTask')}</span>
        </button>
        <button type="button" className="session-shortcut" data-testid="sidebar-scheduled" onClick={onOpenScheduled}>
          <Clock aria-hidden="true" size={14} />
          <span>{t('scheduled')}</span>
        </button>
        <button type="button" className="session-shortcut" data-testid="sidebar-plugins" onClick={onOpenPlugins}>
          <Puzzle aria-hidden="true" size={14} />
          <span>{t('plugins')}</span>
        </button>
        {onOpenSettings !== undefined ? (
          <button type="button" className="session-shortcut" data-testid="sidebar-more" onClick={onOpenSettings}>
            <MoreHorizontal aria-hidden="true" size={14} />
            <span>{t('more')}</span>
          </button>
        ) : null}
      </nav>
      <div className="session-scroll">
      {loading ? (
        <p className="empty-hint" data-testid="session-loading">{t('sessionLoading')}</p>
      ) : error !== null ? (
        <p className="empty-hint" data-testid="session-error">{error || t('sessionError')}</p>
      ) : (
        <>
          {renderCategory('pinned', t('pinned'), resolve(buckets.pinned))}
          <section className="session-category" data-testid="session-category-projects">
            <div className="session-category-head">
              <button
                type="button"
                className="session-category-title"
                aria-expanded={fold.projects}
                onClick={() => toggle('projects')}
              >
                {t('projects')}
                <span className="session-category-chevron" style={{ marginLeft: CHEVRON_GAP_PX }}>
                  {chevron(fold.projects)}
                </span>
              </button>
              {onAddProject !== undefined ? (
                <button
                  type="button"
                  className="session-head-action"
                  data-testid="add-project"
                  title={t('addProject')}
                  aria-label={t('addProject')}
                  onClick={onAddProject}
                  disabled={disabled}
                >
                  <Plus aria-hidden="true" size={14} />
                </button>
              ) : null}
            </div>
            {fold.projects && projectSections.length === 0 ? (
              <p className="empty-hint" data-testid="session-category-projects-empty">{t('emptyProjects')}</p>
            ) : null}
            {fold.projects ? projectSections : null}
          </section>
          {renderCategory(
            'recent',
            t('recent'),
            resolve(buckets.recent),
            <button
              type="button"
              className="session-head-action"
              data-testid="new-in-recent"
              title={t('newTask')}
              aria-label={t('newTask')}
              onClick={onCreate}
              disabled={disabled}
            >
              <Plus aria-hidden="true" size={14} />
            </button>
          )}
        </>
      )}
      </div>
      {onOpenSettings !== undefined && (
        <button
          type="button"
          className="settings-entry"
          data-testid="open-settings"
          data-radius={SETTINGS_ENTRY.borderRadiusPx}
          aria-label={t('openSettings')}
          onClick={onOpenSettings}
        >
          <Settings aria-hidden="true" size={16} />
          <span>{t('settings')}</span>
        </button>
      )}
    </aside>
  )
}

export default SessionList
