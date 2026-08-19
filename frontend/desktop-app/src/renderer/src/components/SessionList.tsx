import { Pencil, Plus, RotateCcw, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { RunState, SessionEntry } from '../lib/conversationStore.mts'

interface SessionListProps {
  sessions: SessionEntry[]
  activeSessionId: string | null
  runStateBySession?: Record<string, RunState>
  childCountBySession?: Record<string, number>
  disabled: boolean
  onCreate: () => void
  onSelect: (sessionId: string) => void
  onRename?: (sessionId: string, title: string) => void
  onTrash?: (sessionId: string) => void
  onRestore?: (sessionId: string) => void
  onPurge?: (sessionId: string) => void
}

function SessionList({
  sessions,
  activeSessionId,
  runStateBySession = {},
  childCountBySession = {},
  disabled,
  onCreate,
  onSelect,
  onRename,
  onTrash,
  onRestore,
  onPurge
}: SessionListProps): React.JSX.Element {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [showTrash, setShowTrash] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [purgeId, setPurgeId] = useState<string | null>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)
  const purgeCancelRef = useRef<HTMLButtonElement>(null)
  const normalizedQuery = query.trim().toLowerCase()
  const matches = (session: SessionEntry): boolean =>
    normalizedQuery === '' || `${session.title} ${session.workspaceRoot}`.toLowerCase().includes(normalizedQuery)
  const activeTasks = useMemo(
    () => sessions.filter((session) => session.trashedAt === null && matches(session)),
    [sessions, normalizedQuery]
  )
  const trashedTasks = useMemo(
    () => sessions.filter((session) => session.trashedAt !== null && matches(session)),
    [sessions, normalizedQuery]
  )

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
                aria-label={`Rename ${session.title}`}
                data-testid={`rename-input-${session.sessionId}`}
              />
              <button type="submit" className="rename-save" data-testid={`rename-save-${session.sessionId}`}>{t('save')}</button>
              <button type="button" className="rename-cancel" data-testid={`rename-cancel-${session.sessionId}`} onClick={() => { setRenamingId(null); setRenameValue('') }}>{t('cancel')}</button>
            </form>
          ) : (
            <button
              type="button"
              className={`session-item${session.sessionId === activeSessionId ? ' active' : ''}`}
              onClick={() => onSelect(session.sessionId)}
              disabled={trashed}
              data-testid={`session-${session.sessionId}`}
            >
              <span className="session-title-row">
                <span className="session-title">{session.title}</span>
                {!trashed && <span className={'session-state state-' + state}>{state === 'succeeded' ? 'ready' : state}</span>}
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

  return (
    <aside className="session-panel" data-testid="session-nav" aria-label="Tasks and sessions">
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
      {activeTasks.length === 0 && trashedTasks.length === 0 ? (
        <p className="empty-hint">{t('emptyTasks')}</p>
      ) : (
        <>
          {activeTasks.length > 0 && <ul className="session-list">{activeTasks.map((session) => renderTask(session, false))}</ul>}
          {trashedTasks.length > 0 && (
            <section className="recently-deleted">
              <button type="button" className="trash-toggle" aria-expanded={showTrash} onClick={() => setShowTrash((value) => !value)}>
                {t('recentlyDeleted')} ({trashedTasks.length})
              </button>
              {showTrash && <ul className="session-list trashed-list">{trashedTasks.map((session) => renderTask(session, true))}</ul>}
            </section>
          )}
        </>
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
