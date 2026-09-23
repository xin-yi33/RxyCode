import { Archive, Clock, Folder, MoreHorizontal, Pin, Plus, Puzzle, Search, Settings } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import {
  CHEVRON_GAP_PX,
  chevron,
  HOVER_DARK,
  HOVER_LIGHT,
  looksRecentWorkspace,
  projectCategories,
  projectNeedsExpand,
  visibleProjectSessions,
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
import { TitleMarquee } from '../../../features/sessions/TitleMarquee.ts'
import { sharedMarqueePxPerSec } from '../../../features/sessions/titleMarqueeMath.ts'
import { SessionContextMenu, type SessionContextAction } from '../../../features/sessions/SessionContextMenu.ts'
import { ProjectContextMenu, type ProjectContextAction } from '../../../features/projects/ProjectContextMenu.ts'
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
  onMarkUnread?: (sessionId: string, unread: boolean) => void
  onOpenSettings?: () => void
  onOpenScheduled?: () => void
  onOpenPlugins?: () => void
  pluginsOpen?: boolean
  hiddenCwds?: readonly string[]
  onProjectAction?: (cwd: string, action: ProjectContextAction) => void
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
    projectId: looksRecentWorkspace(session.workspaceRoot) ? null : session.workspaceRoot
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
  onMarkUnread,
  onOpenSettings,
  onOpenScheduled,
  onOpenPlugins,
  pluginsOpen = false,
  hiddenCwds = [],
  onProjectAction
}: SessionListProps): React.JSX.Element {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [fold, setFold] = useState<FoldState>(() => loadFold(typeof window === 'undefined' ? undefined : window.localStorage))
  const [expandedProjects, setExpandedProjects] = useState<Record<string, boolean>>({})
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

  const [menu, setMenu] = useState<{ sessionId: string; x: number; y: number } | null>(null)
  const [projectMenu, setProjectMenu] = useState<{ cwd: string; x: number; y: number } | null>(null)
  const [renamingProject, setRenamingProject] = useState<string | null>(null)
  const [projectRenameValue, setProjectRenameValue] = useState('')
  const [overflowById, setOverflowById] = useState<Record<string, number>>({})
  const reportOverflow = useCallback((sessionId: string, overflowPx: number) => {
    setOverflowById((current) =>
      current[sessionId] === overflowPx ? current : { ...current, [sessionId]: overflowPx }
    )
  }, [])
  const titlePxPerSec = useMemo(
    () => sharedMarqueePxPerSec(Object.values(overflowById)),
    [overflowById]
  )

  useEffect(() => {
    if (renamingId !== null) renameInputRef.current?.focus()
  }, [renamingId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (activeSessionId === null || renamingId !== null) return
      const target = event.target as HTMLElement | null
      if (target !== null && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      const session = sessionById.get(activeSessionId)
      if (session === undefined) return
      const pinned = session.pinned || pinnedIds.includes(session.sessionId)
      if (event.altKey && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') {
        event.preventDefault()
        onPin?.(session.sessionId, !pinned)
      }
      if (event.altKey && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'r') {
        event.preventDefault()
        requestRename(session)
      }
      if (event.shiftKey && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'u') {
        event.preventDefault()
        onMarkUnread?.(session.sessionId, !unreadIds.includes(session.sessionId))
      }
      if (event.shiftKey && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault()
        onTrash?.(session.sessionId)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [activeSessionId, renamingId, sessionById, pinnedIds, unreadIds, onPin, onMarkUnread, onTrash])

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
      <li
        key={session.sessionId}
        className={
          'session-row' +
          (chrome === 'unread' ? ' has-unread' : '') +
          (session.sessionId === activeSessionId ? ' is-active' : '') +
          (chrome === 'spin' ? ' is-running' : '')
        }
        onContextMenu={(event) => {
          if (trashed) return
          event.preventDefault()
          setMenu({ sessionId: session.sessionId, x: event.clientX, y: event.clientY })
        }}
      >
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
                {chrome === 'spin' ? <StatusIndicator backend="running" visualState={visual} /> : null}
                <TitleMarquee
                  className="session-title"
                  text={session.title}
                  testId={`title-${session.sessionId}`}
                  pxPerSec={titlePxPerSec}
                  onOverflow={(overflowPx) => reportOverflow(session.sessionId, overflowPx)}
                />
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
    ),
    hiddenCwds
  )
  const projectSections = projectRows.map((row) => (
    <section key={row.cwd} className="session-project" data-testid={`session-project-${row.cwd}`}>
      <div
        className="session-project-head"
        onContextMenu={(event) => {
          event.preventDefault()
          setProjectMenu({ cwd: row.cwd, x: event.clientX, y: event.clientY })
        }}
      >
        <Folder className="session-project-folder" aria-hidden="true" size={14} />
        {renamingProject === row.cwd ? (
          <form
            className="session-rename-form"
            onSubmit={(event) => {
              event.preventDefault()
              const next = projectRenameValue.trim()
              if (next !== '') onProjectAction?.(row.cwd, { kind: 'edit', name: next })
              setRenamingProject(null)
            }}
          >
            <input
              autoFocus
              value={projectRenameValue}
              onChange={(event) => setProjectRenameValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  setRenamingProject(null)
                }
              }}
              aria-label={`${t('editProject')} ${row.displayName}`}
              data-testid={`rename-project-${row.cwd}`}
            />
          </form>
        ) : (
          <p className="session-project-title" title={row.cwd}>{row.displayName}</p>
        )}
        <div className="session-project-actions">
          <button
            type="button"
            className="session-head-action"
            data-testid={`project-more-${row.cwd}`}
            title={t('projectMore')}
            aria-label={t('projectMore')}
            onClick={(event) => {
              event.stopPropagation()
              const box = event.currentTarget.getBoundingClientRect()
              setProjectMenu({ cwd: row.cwd, x: box.right, y: box.bottom })
            }}
          >
            <MoreHorizontal aria-hidden="true" size={14} />
          </button>
          {onCreateInProject !== undefined ? (
            <button
              type="button"
              className="session-head-action"
              data-testid={`new-in-project-${row.cwd}`}
              title={t('newInProject')}
              aria-label={t('newInProject')}
              onClick={() => {
                onCreateInProject(row.cwd)
              }}
              disabled={disabled}
            >
              <Plus aria-hidden="true" size={14} />
            </button>
          ) : null}
        </div>
      </div>
      {(() => {
        const all = sessionsForCwd(row.cwd)
        const expanded = normalizedQuery !== '' || expandedProjects[row.cwd] === true
        const shown = visibleProjectSessions(all, expanded)
        return (
          <>
            <ul className="session-list session-list-in-project">{shown.map((session) => renderTask(session, false))}</ul>
            {projectNeedsExpand(all.length) && !expanded ? (
              <button
                type="button"
                className="session-project-expand"
                data-testid={`expand-project-${row.cwd}`}
                onClick={() => setExpandedProjects((current) => ({ ...current, [row.cwd]: true }))}
              >
                {t('expandShow')}
              </button>
            ) : null}
          </>
        )
      })()}
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
        <button type="button" className="session-shortcut" data-testid="sidebar-new" onClick={() => {
          onCreate()
        }} disabled={disabled}>
          <Plus aria-hidden="true" size={14} />
          <span>{t('newTask')}</span>
        </button>
        <button type="button" className="session-shortcut" data-testid="sidebar-scheduled" onClick={onOpenScheduled}>
          <Clock aria-hidden="true" size={14} />
          <span>{t('scheduled')}</span>
        </button>
        {onOpenPlugins !== undefined ? (
          <button
            type="button"
            className={'session-shortcut' + (pluginsOpen ? ' is-active' : '')}
            data-testid="sidebar-plugins"
            aria-pressed={pluginsOpen}
            onClick={onOpenPlugins}
          >
            <Puzzle aria-hidden="true" size={14} />
            <span>{t('plugins')}</span>
          </button>
        ) : null}
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
              onClick={() => {
                onCreate()
              }}
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
      {menu !== null && sessionById.get(menu.sessionId) !== undefined ? (
        <SessionContextMenu
          x={menu.x}
          y={menu.y}
          sessionId={menu.sessionId}
          title={sessionById.get(menu.sessionId)?.title ?? ''}
          pinned={sessionById.get(menu.sessionId)?.pinned === true || pinnedIds.includes(menu.sessionId)}
          unread={unreadIds.includes(menu.sessionId)}
          currentProject={
            looksRecentWorkspace(sessionById.get(menu.sessionId)?.workspaceRoot ?? '')
              ? null
              : (sessionById.get(menu.sessionId)?.workspaceRoot ?? null)
          }
          projects={projectRows.map((row) => ({ cwd: row.cwd, displayName: row.displayName }))}
          labels={{
            pin: t('pinTask'),
            unpin: t('unpinTask'),
            rename: t('renameChat'),
            unread: t('markUnread'),
            archive: t('archiveChat'),
            project: t('projects'),
            section: t('section'),
            share: t('share'),
            copy: t('copy'),
            copyTitle: t('copyTitle'),
            copyId: t('copyId'),
            openInNewWindow: t('openInNewWindow'),
            recent: t('recent')
          }}
          onClose={() => setMenu(null)}
          onAction={(action: SessionContextAction) => {
            const session = sessionById.get(menu.sessionId)
            if (session === undefined) return
            if (action.kind === 'pin') onPin?.(session.sessionId, !(session.pinned || pinnedIds.includes(session.sessionId)))
            if (action.kind === 'rename') requestRename(session)
            if (action.kind === 'unread') onMarkUnread?.(session.sessionId, !unreadIds.includes(session.sessionId))
            if (action.kind === 'archive') onTrash?.(session.sessionId)
            if (action.kind === 'section') onPin?.(session.sessionId, action.section === 'pinned')
            if (action.kind === 'share' || (action.kind === 'copy' && action.field === 'title')) {
              void navigator.clipboard?.writeText(session.title)
            }
            if (action.kind === 'copy' && action.field === 'id') void navigator.clipboard?.writeText(session.sessionId)
          }}
        />
      ) : null}
      {projectMenu !== null ? (
        <ProjectContextMenu
          x={projectMenu.x}
          y={projectMenu.y}
          pinned={projectRows.find((row) => row.cwd === projectMenu.cwd)?.pinned === true}
          labels={{
            pin: t('pinTask'),
            unpin: t('unpinTask'),
            edit: t('editProject'),
            section: t('section'),
            reveal: t('openInExplorer'),
            createWorktree: t('createPermanentWorktree'),
            archiveChats: t('archiveProjectChats'),
            removeProject: t('removeProject'),
            recent: t('recent')
          }}
          onClose={() => setProjectMenu(null)}
          onAction={(action: ProjectContextAction) => {
            if (action.kind === 'edit' && action.name === undefined) {
              const row = projectRows.find((row) => row.cwd === projectMenu.cwd)
              setRenamingProject(projectMenu.cwd)
              setProjectRenameValue(row?.displayName ?? '')
              return
            }
            onProjectAction?.(projectMenu.cwd, action)
          }}
        />
      ) : null}
    </aside>
  )
}

export default SessionList
