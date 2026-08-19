import { Pencil, Plus, RotateCcw, Search, Settings, Trash2 } from 'lucide-react'
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
import { fromSessionRunState } from '../../../lib/statusProjection.ts'
import { SETTINGS_ENTRY } from '../../../lib/settingsSections.ts'
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
  onCreate: () => void
  onSelect: (sessionId: string) => void
  onRename?: (sessionId: string, title: string) => void
  onTrash?: (sessionId: string) => void
  onRestore?: (sessionId: string) => void
  onPurge?: (sessionId: string) => void
  onOpenSettings?: () => void
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
    pinned: pinned.has(session.sessionId),
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
  onCreate,
  onSelect,
  onRename,
  onTrash,
  onRestore,
  onPurge,
  onOpenSettings
}: SessionListProps): React.JSX.Element {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [fold, setFold] = useState<FoldState>(() => loadFold(typeof window === 'undefined' ? undefined : window.localStorage))
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [purgeId, setPurgeId] = useState<string | null>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)
  const purgeCancelRef = useRef<HTMLButtonElement>(null)
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

  useEffect(() => {
    if (purgeId === null) return
    purgeCancelRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setPurgeId(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [purgeId])

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
    return (
      <li key={session.sessionId} className="session-row">
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
              className={`session-item${session.sessionId === activeSessionId ? ' active' : ''}${!trashed && fromSessionRunState(state) === 'running' ? ' is-running' : ''}`}
              onClick={() => onSelect(session.sessionId)}
              disabled={trashed}
              data-testid={`session-${session.sessionId}`}
            >
              <span className="session-title-row">
                <span className="session-title">{session.title}</span>
                {!trashed && <StatusIndicator backend={fromSessionRunState(state)} visualState={visual} />}
              </span>
              <span className="session-id">{session.sessionId}</span>
              <span className="session-workspace" title={session.workspaceRoot}>{session.workspaceRoot}</span>
              {childCount > 0 && <span className="session-child-count">{childCount} child agents</span>}
            </button>
          )}
        </div>
        <div className="session-actions" aria-label={`${session.title} actions`}>
          {trashed ? (
            <>
              <button type="button" className="icon-button" title={t('restore')} aria-label={t('restore')} data-testid={`restore-task-${session.sessionId}`} onClick={() => onRestore?.(session.sessionId)}>
                <RotateCcw aria-hidden="true" size={14} />
              </button>
              <button type="button" className="icon-button danger" title={t('deletePermanently')} aria-label={t('deletePermanently')} data-testid={`purge-task-${session.sessionId}`} onClick={() => {
                setPurgeId(session.sessionId)
              }}>
                <Trash2 aria-hidden="true" size={14} />
              </button>
            </>
          ) : (
            <>
              <button type="button" className="icon-button" title={t('rename')} aria-label={t('rename')} data-testid={`rename-task-${session.sessionId}`} onClick={() => requestRename(session)}>
                <Pencil aria-hidden="true" size={14} />
              </button>
              <button type="button" className="icon-button danger" title={t('moveToDeleted')} aria-label={t('moveToDeleted')} data-testid={`trash-task-${session.sessionId}`} onClick={() => onTrash?.(session.sessionId)}>
                <Trash2 aria-hidden="true" size={14} />
              </button>
            </>
          )}
        </div>
      </li>
    )
  }

  const renderCategory = (
    id: keyof FoldState,
    title: string,
    items: SessionEntry[]
  ): React.JSX.Element => {
    const expanded = fold[id]
    return (
      <section className="session-category" data-testid={`session-category-${id}`}>
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

  const projectSections = Object.entries(buckets.projects).map(([projectId, entries]) => (
    <section key={projectId} className="session-project" data-testid={`session-project-${projectId}`}>
      <p className="session-project-title">{projectId}</p>
      <ul className="session-list">{resolve(entries).map((session) => renderTask(session, false))}</ul>
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
      {loading ? (
        <p className="empty-hint" data-testid="session-loading">{t('sessionLoading')}</p>
      ) : error !== null ? (
        <p className="empty-hint" data-testid="session-error">{error || t('sessionError')}</p>
      ) : (
        <>
          {renderCategory('pinned', t('pinned'), resolve(buckets.pinned))}
          <section className="session-category" data-testid="session-category-projects">
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
            {fold.projects ? projectSections : null}
          </section>
          {renderCategory('recent', t('recent'), resolve(buckets.recent))}
          <section className="session-category recycle" data-testid="session-recycle">
            <p className="session-category-title">{t('recycle')}</p>
            {buckets.recycleBlocked ? (
              <p className="blocked-badge" data-testid="session-recycle-blocked">
                {t('blocked')}: {t('recycleBlockedDetail')}
              </p>
            ) : (
              <ul className="session-list trashed-list">
                {sessions.filter((session) => session.trashedAt !== null).map((session) => renderTask(session, true))}
              </ul>
            )}
          </section>
        </>
      )}
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
      {purgeId !== null && (
        <div className="task-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPurgeId(null) }}>
          <section className="task-dialog" role="dialog" aria-modal="true" aria-labelledby="purge-task-title" data-testid="purge-dialog">
            <p className="inspector-eyebrow">{t('permanentAction')}</p>
            <h2 id="purge-task-title">{t('purgeTitle')}</h2>
            <p>{t('purgeBody')}</p>
            <div className="task-dialog-actions">
              <button ref={purgeCancelRef} type="button" onClick={() => setPurgeId(null)}>{t('cancel')}</button>
              <button type="button" className="danger" onClick={() => { onPurge?.(purgeId); setPurgeId(null) }}>{t('deletePermanently')}</button>
            </div>
          </section>
        </div>
      )}
    </aside>
  )
}

export default SessionList
