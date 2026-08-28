import { Activity, LayoutGrid, Menu, Settings, ShieldCheck, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { DESKTOP_VIEWS, resolveDesktopView, type DesktopViewId } from '../../app/views/index.ts'
import { BoardView } from '../../features/board/BoardView.ts'
import { sessionsToBoardThreads } from '../../features/board/board.selectors.ts'
import { ApprovalCard } from '../../features/approvals/ApprovalCard.ts'
import { approvalChannel } from '../../features/approvals/approval.mode.ts'
import { pushPending, type PendingItem, type SendIntent } from '../../features/composer/pending.queue.ts'
import ApprovalModal from './components/ApprovalModal'
import QuestionModal from './components/QuestionModal'
import ApprovalRulesModal from './components/ApprovalRulesModal'
import ChatArea from './components/ChatArea'
import Composer from './components/Composer'
import GoalDialog from './components/GoalDialog'
import SessionList from './components/SessionList'
import SettingsPage from './components/SettingsPage'
import TaskHeader from './components/TaskHeader'
import TaskInspector from './components/TaskInspector'
import { useConversation } from './hooks/useConversation'
import { useModels } from './hooks/useModels'
import type { TimelineItem } from './lib/conversationStore.mts'
import { canTrashTask } from './lib/taskActions.mts'
import { modelStatusLabel } from './lib/taskPresentation.mts'
import { isClearGoalText, parseComposerCommand } from './lib/composerCommands.mts'
import { applyGoalToPrompt, loadSessionGoals, saveSessionGoals } from './lib/goalSettings.mts'
import {
  buildImplementPrompt,
  buildRevisePrompt,
  planModeInstruction,
  type AgentRunMode
} from './lib/planDocument.mts'
import { latestPlanFromTimeline } from './lib/planTimeline.mts'
import {
  effectiveWorkspaceRoot,
  loadWorkspaceSettings,
  normalizeWorkspaceRoot,
  saveWorkspaceSettings,
  type WorkspaceSettings
} from './lib/workspaceSettings.mts'
import { isUiEntryEnabled } from '../../protocol/capabilityGate.ts'
import { recycleSectionModel } from '../../features/recycle/recycle.probe.ts'
import { usePlatform } from '../../platform/index.mts'
import {
  DESKTOP_PREFERENCES_STORAGE_KEY,
  loadDesktopPreferences,
  saveDesktopPreferences,
  type DesktopLanguage,
  type PermissionMode,
  type ThemePreference
} from './lib/desktopPreferences.mts'
import { I18nProvider } from '../../i18n/I18nContext.tsx'
import { normalizeLocale, t } from '../../i18n/t.ts'
import {
  dispatchRunEndNotice,
  electronOsNotify,
  watchRunStateTransitions,
  type Notice
} from '../../features/notifications/notify.ts'
import { workbenchLayoutClass } from '../../features/shell/workbenchLayout.ts'
import { RunPanel } from '../../features/runpanel/RunPanel.ts'
import { projectRunPanel } from '../../features/runpanel/runPanel.model.ts'
import { Statusline } from '../../components/statusbar/Statusline.ts'
import { PromptSuggestions } from '../../features/composer/PromptSuggestions.ts'

const EMPTY_USAGE = {
  inputTokens: null,
  outputTokens: null,
  cacheHitTokens: null,
  cacheWriteTokens: null,
  cacheHitRate: null,
  reportingStatus: 'not_reported' as const
}

function App(): React.JSX.Element {
  const { platform, info, status } = usePlatform()
  const [workspaceSettings, setWorkspaceSettings] = useState<WorkspaceSettings>(() =>
    loadWorkspaceSettings(window.localStorage)
  )
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pickingWorkspace, setPickingWorkspace] = useState(false)
  const [rulesOpen, setRulesOpen] = useState(false)
  const [preferences, setPreferences] = useState(() => loadDesktopPreferences(window.localStorage))
  const { theme, permissionMode, language } = preferences
  const [pendingFullAuto, setPendingFullAuto] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectorItem, setInspectorItem] = useState<TimelineItem | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [agentModeBySession, setAgentModeBySession] = useState<Record<string, AgentRunMode>>({})
  const [sessionGoals, setSessionGoals] = useState(() => loadSessionGoals(window.localStorage))
  const [goalOpen, setGoalOpen] = useState(false)
  const [goalDraft, setGoalDraft] = useState('')
  const [skippedPlanIds, setSkippedPlanIds] = useState<Record<string, true>>({})
  const toastTimerRef = useRef<number | null>(null)
  const prevRunStateRef = useRef<Record<string, string>>({})
  const [runBanner, setRunBanner] = useState<Notice | null>(null)
  const [desktopView, setDesktopView] = useState<DesktopViewId>('chat')
  const [commandOpen, setCommandOpen] = useState(false)
  const [pendingBySession, setPendingBySession] = useState<Record<string, PendingItem[]>>({})
  const conversation = useConversation(platform, info, status, workspaceSettings.workspaceRoot)
  const sessionListEnabled = isUiEntryEnabled(conversation.handshakeCapabilities, 'sessionList')
  const approvalEnabled = isUiEntryEnabled(conversation.handshakeCapabilities, 'approvalModal')
  const activeSessionId = conversation.state.activeSessionId
  const running = activeSessionId !== null && conversation.state.runningBySession[activeSessionId]
  const activeSession = conversation.state.sessions.find((session) => session.sessionId === activeSessionId)
  const activeRunState =
    activeSessionId === null ? 'succeeded' : conversation.state.runStateBySession[activeSessionId] ?? 'succeeded'
  const childCountBySession = Object.fromEntries(
    Object.entries(conversation.state.childSessionsByRoot).map(([sessionId, children]) => [
      sessionId,
      children.length
    ])
  )
  const activeChildSessions =
    activeSessionId === null ? [] : (conversation.state.childSessionsByRoot[activeSessionId] ?? [])
  const pendingApproval = conversation.state.approvals[0] ?? null
  const pendingQuestion = conversation.pendingQuestion
  const effectiveWorkspace = effectiveWorkspaceRoot(workspaceSettings, info?.repoRoot ?? '')
  const models = useModels({
    client: conversation.protocolClient,
    refreshKey: settingsOpen ? 1 : 0,
    capabilities: conversation.handshakeCapabilities
  })
  const selectedTaskModel = activeSession?.modelId ?? models.snapshot?.active ?? ''
  const agentMode: AgentRunMode =
    activeSessionId === null ? 'build' : (agentModeBySession[activeSessionId] ?? 'build')
  const activeGoal = activeSessionId === null ? '' : (sessionGoals[activeSessionId] ?? '')
  const activeTimeline =
    activeSessionId !== null ? (conversation.state.timelineBySession[activeSessionId] ?? []) : []
  const latestPlan = latestPlanFromTimeline(activeTimeline)
  const showPlanActions =
    latestPlan !== null &&
    skippedPlanIds[latestPlan.itemId] !== true &&
    !running

  const setAgentMode = (next: AgentRunMode): void => {
    if (activeSessionId === null) return
    setAgentModeBySession((current) => ({ ...current, [activeSessionId]: next }))
  }

  const locale = normalizeLocale(language)
  const tr = (key: string, vars: Record<string, string> = {}): string => t(locale, key, vars)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.lang = language
    saveDesktopPreferences(preferences, window.localStorage)
  }, [preferences, theme, language])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey)) return
      if (event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (info?.systemLocale === undefined) return
    if (window.localStorage.getItem(DESKTOP_PREFERENCES_STORAGE_KEY) !== null) return
    const next: DesktopLanguage = normalizeLocale(info.systemLocale) === 'en' ? 'en-US' : 'zh-CN'
    setPreferences((current) => (current.language === next ? current : { ...current, language: next }))
  }, [info])

  const setTheme = (next: ThemePreference): void => {
    setPreferences((current) => ({ ...current, theme: next }))
  }

  const setLanguage = (next: DesktopLanguage): void => {
    setPreferences((current) => ({ ...current, language: next }))
  }

  const requestPermissionModeChange = (next: PermissionMode): void => {
    if (next === 'full_auto' && permissionMode !== 'full_auto') {
      setPendingFullAuto(true)
      return
    }
    setPreferences((current) => ({ ...current, permissionMode: next }))
  }

  const pickWorkspace = async (): Promise<boolean> => {
    setPickingWorkspace(true)
    try {
      const picked = await platform.pickWorkspaceDirectory()
      if (picked !== null) {
        const next: WorkspaceSettings = { workspaceRoot: normalizeWorkspaceRoot(picked) }
        setWorkspaceSettings(next)
        saveWorkspaceSettings(next, window.localStorage)
        return true
      }
      return false
    } finally {
      setPickingWorkspace(false)
    }
  }

  const clearWorkspace = (): void => {
    const next: WorkspaceSettings = { workspaceRoot: null }
    setWorkspaceSettings(next)
    saveWorkspaceSettings(next, window.localStorage)
  }

  const openInspector = (item: TimelineItem): void => {
    setInspectorItem(item)
    setInspectorOpen(true)
  }

  const showToast = (message: string): void => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    setToast(message)
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null)
      toastTimerRef.current = null
    }, 3200)
  }

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
  }, [])

  useEffect(() => {
    const next = conversation.state.runStateBySession
    const transitions = watchRunStateTransitions(prevRunStateRef.current, next)
    prevRunStateRef.current = { ...next }
    for (const event of transitions) {
      dispatchRunEndNotice(event.sessionId, event.state, {
        osNotify: electronOsNotify,
        showBanner: (notice) => setRunBanner(notice)
      })
    }
  }, [conversation.state.runStateBySession])

  useEffect(() => {
    if (!settingsOpen) return
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      setSettingsOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape, true)
    return () => window.removeEventListener('keydown', closeOnEscape, true)
  }, [settingsOpen])

  useEffect(() => {
    if (!navOpen) return
    const closeNavigationOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      setNavOpen(false)
    }
    window.addEventListener('keydown', closeNavigationOnEscape, true)
    return () => window.removeEventListener('keydown', closeNavigationOnEscape, true)
  }, [navOpen])

  useEffect(() => {
    if (!pendingFullAuto) return
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      setPendingFullAuto(false)
    }
    window.addEventListener('keydown', closeOnEscape, true)
    return () => window.removeEventListener('keydown', closeOnEscape, true)
  }, [pendingFullAuto])

  const persistGoal = (sessionId: string, value: string): void => {
    setSessionGoals((current) => {
      const next = { ...current }
      const trimmed = value.trim()
      if (trimmed === '') delete next[sessionId]
      else next[sessionId] = trimmed
      saveSessionGoals(next, window.localStorage)
      return next
    })
  }

  const openGoalDialog = (): void => {
    setGoalDraft(activeGoal)
    setGoalOpen(true)
  }

  const sendTurn = async (displayText: string, mode: AgentRunMode, promptText?: string): Promise<void> => {
    setToast(null)
    const previousPlan = mode === 'plan' ? latestPlan?.document ?? null : null
    let body = promptText
    if (body === undefined) {
      body = mode === 'plan'
        ? (previousPlan === null ? `${planModeInstruction()}\n\n${displayText}` : buildRevisePrompt(previousPlan, displayText))
        : displayText
    }
    await conversation.sendMessage(displayText, {
      permissionMode,
      mode,
      promptText: applyGoalToPrompt(activeGoal, body)
    })
  }

  const handleComposerSend = async (text: string): Promise<void> => {
    const command = parseComposerCommand(text)
    if (command?.kind === 'slash_plan') {
      setAgentMode('plan')
      if (command.rest === '') {
        showToast(tr('planModeOn'))
        return
      }
      await sendTurn(command.rest, 'plan')
      return
    }
    if (command?.kind === 'slash_build') {
      setAgentMode('build')
      if (command.rest === '') {
        showToast(tr('agentModeOn'))
        return
      }
      await sendTurn(command.rest, 'build')
      return
    }
    if (command?.kind === 'slash_goal') {
      if (command.rest === '') {
        openGoalDialog()
        return
      }
      if (activeSessionId === null) return
      if (isClearGoalText(command.rest)) {
        persistGoal(activeSessionId, '')
        showToast(tr('goalCleared'))
        return
      }
      persistGoal(activeSessionId, command.rest)
      showToast(tr('goalSaved'))
      return
    }
    await sendTurn(text, agentMode)
  }

  const handleSendIntent = async (intent: SendIntent, text: string): Promise<void> => {
    if (intent === 'queue') {
      if (activeSessionId === null) return
      setPendingBySession((current) => ({
        ...current,
        [activeSessionId]: pushPending(current[activeSessionId] ?? [], {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          text
        })
      }))
      return
    }
    if (intent === 'steer') {
      const client = conversation.protocolClient
      if (client === null || text.trim() === '') return
      try {
        await client.request('turn/steer', { text })
      } catch (error) {
        showToast(tr('connectionFailed', { error: error instanceof Error ? error.message : String(error) }))
      }
      return
    }
    await conversation.interrupt()
    if (text.trim() !== '') await handleComposerSend(text)
  }

  const handleCreate = async (): Promise<void> => {
    // Navigation is independent from the session/new RPC. Close the drawer
    // immediately so a slow server warm cannot make the click look stuck.
    setNavOpen(false)
    showToast(tr('creatingTask'))
    const selected = models.snapshot?.models.find((model) => model.id === selectedTaskModel)
    const created = await conversation.createSession({
      modelId: selectedTaskModel || undefined,
      providerId: selected?.provider_id ?? null
    })
    showToast(created ? tr('taskCreated') : tr('taskCreateFailed'))
  }

  const handlePickWorkspaceForChat = async (): Promise<void> => {
    setPickingWorkspace(true)
    try {
      const picked = await platform.pickWorkspaceDirectory()
      if (picked === null) return
      const workspaceRoot = normalizeWorkspaceRoot(picked)
      if (workspaceRoot === null) return
      const next: WorkspaceSettings = { workspaceRoot }
      setWorkspaceSettings(next)
      saveWorkspaceSettings(next, window.localStorage)
      setNavOpen(false)
      showToast(tr('creatingTaskInProject'))
      const selected = models.snapshot?.models.find((model) => model.id === selectedTaskModel)
      const created = await conversation.createSession({
        modelId: selectedTaskModel || undefined,
        providerId: selected?.provider_id || undefined,
        workspaceRoot
      })
      showToast(created ? tr('taskCreatedInProject') : tr('taskCreatePartialFail'))
    } finally {
      setPickingWorkspace(false)
    }
  }

  const handleTrash = async (sessionId: string): Promise<void> => {
    const decision = canTrashTask(activeSessionId, sessionId)
    if (!decision.allowed) {
      showToast(decision.message ?? tr('cannotDeleteTask'))
      return
    }
    const operation = conversation.trashSession(sessionId)
    showToast(tr('taskDeleted'))
    if (!(await operation)) showToast(tr('deleteNotSaved'))
  }

  const handleRestore = async (sessionId: string): Promise<void> => {
    const operation = conversation.restoreSession(sessionId)
    showToast(tr('taskRestored'))
    if (!(await operation)) showToast(tr('restoreNotSaved'))
  }

  const recycleModel = recycleSectionModel({
    listDeletedAvailable: true,
    sessions: conversation.state.sessions
  })
  const runPanel = activeSessionId === null
    ? null
    : projectRunPanel(conversation.state, activeSessionId)

  const handlePurgeRecycle = async (): Promise<void> => {
    const ids = recycleModel.items.map((item) => item.id)
    for (const id of ids) {
      if (!(await conversation.purgeSession(id))) showToast(tr('deleteNotSaved'))
    }
  }

  return (
    <I18nProvider locale={locale}>
    <div className="workspace command-center" data-testid="task-command-center">
      <a className="skip-link" href="#task-main">{tr('skipToTask')}</a>
      <header className="topbar command-topbar">
        <div className="topbar-leading">
          <button
            type="button"
            className="icon-button nav-toggle"
            aria-label={tr('openNav')}
            onClick={() => setNavOpen(true)}
          >
            <Menu aria-hidden="true" size={18} />
          </button>
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">R</span>
            <span>RxyCode</span>
            <span className="brand-product">{tr('desktop')}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <span className={'connection-status ' + status}>
            <Activity aria-hidden="true" size={14} />
            {status}
          </span>
          <button
            type="button"
            className="icon-button board-button"
            onClick={() => setDesktopView(desktopView === 'board' ? 'chat' : 'board')}
            aria-label={tr('boardView')}
            title={tr('boardView')}
            data-testid="open-board-view"
            aria-pressed={desktopView === 'board'}
          >
            <LayoutGrid aria-hidden="true" size={17} />
          </button>
          <button
            type="button"
            className="icon-button rules-button"
            onClick={() => setRulesOpen(true)}
            aria-label={tr('approvalRules')}
            title={tr('approvalRules')}
          >
            <ShieldCheck aria-hidden="true" size={17} />
          </button>
          <button
            type="button"
            className="icon-button settings-button"
            onClick={() => setSettingsOpen(true)}
            aria-label={tr('openSettings')}
            title={tr('openSettings')}
          >
            <Settings aria-hidden="true" size={17} />
          </button>
        </div>
      </header>

      <div
        className={workbenchLayoutClass({
          inspectorOpen,
          runPanelOpen: !inspectorOpen && (runPanel?.open === true),
          navOpen
        })}
        data-testid="workbench-layout"
      >
        <div className={'mobile-sheet nav-sheet' + (navOpen ? ' open' : '')}>
          <button type="button" className="sheet-backdrop" aria-label={tr('closeNav')} onClick={() => setNavOpen(false)} />
          <div className="sheet-panel">
            <button type="button" className="sheet-close" aria-label={tr('closeNav')} onClick={() => setNavOpen(false)}>
              <X aria-hidden="true" size={18} />
            </button>
            <SessionList
              sessions={conversation.state.sessions}
              activeSessionId={activeSessionId}
              runStateBySession={conversation.state.runStateBySession}
              childCountBySession={childCountBySession}
              listDeletedAvailable
              disabled={!sessionListEnabled || status !== 'running' || conversation.protocolClient === null}
              onCreate={() => void handleCreate()}
              onSelect={(sessionId) => {
                conversation.selectSession(sessionId)
                setNavOpen(false)
              }}
              onRename={(sessionId, title) => void conversation.renameSession(sessionId, title)}
              onTrash={(sessionId) => void handleTrash(sessionId)}
              onRestore={(sessionId) => void handleRestore(sessionId)}
              onPurge={(sessionId) => void conversation.purgeSession(sessionId)}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          </div>
        </div>

        <div className="desktop-navigation-panel">
        <SessionList
          sessions={conversation.state.sessions}
          activeSessionId={activeSessionId}
          runStateBySession={conversation.state.runStateBySession}
          childCountBySession={childCountBySession}
          listDeletedAvailable
          disabled={!sessionListEnabled || status !== 'running' || conversation.protocolClient === null}
          onCreate={() => void handleCreate()}
          onSelect={conversation.selectSession}
          onRename={(sessionId, title) => void conversation.renameSession(sessionId, title)}
          onTrash={(sessionId) => void handleTrash(sessionId)}
          onRestore={(sessionId) => void handleRestore(sessionId)}
          onPurge={(sessionId) => void conversation.purgeSession(sessionId)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        </div>

        <main className="chat-column task-main" id="task-main" data-testid="task-main">
          {desktopView === 'board' ? (
            <BoardView
              threads={sessionsToBoardThreads(
                conversation.state.sessions,
                conversation.state.runStateBySession,
                Object.fromEntries(
                  Object.entries(conversation.state.timelineBySession).map(([id, items]) => [
                    id,
                    items.length > 0
                  ])
                )
              )}
              loading={status === 'starting'}
              error={conversation.connectionError}
              dark={theme === 'dark'}
              onOpenThread={(sessionId) => {
                conversation.selectSession(sessionId)
                setDesktopView('chat')
              }}
              onRenameThread={(sessionId) => {
                const session = conversation.state.sessions.find((item) => item.sessionId === sessionId)
                const next = window.prompt(tr('rename'), session?.title ?? '')
                if (next !== null && next.trim() !== '') {
                  void conversation.renameSession(sessionId, next.trim())
                }
              }}
              onCancelThread={(sessionId) => {
                if (conversation.state.activeSessionId === sessionId) {
                  void conversation.interrupt()
                }
              }}
              onReviewThread={(sessionId) => {
                conversation.selectSession(sessionId)
                setDesktopView('chat')
                setInspectorOpen(true)
              }}
            />
          ) : null}
          {desktopView === 'chat' ? (
          <>
          <TaskHeader
            title={activeSession?.title ?? 'New task'}
            workspaceRoot={activeSession?.workspaceRoot ?? effectiveWorkspace}
            modelLabel={modelStatusLabel({
              selectedModelId: selectedTaskModel,
              loading: models.loading,
              snapshotLoaded: models.snapshot !== null
            })}
            runState={activeRunState}
          />
          {conversation.connectionError !== null && (
            <div className="error-banner" role="alert">
              {tr('connectionFailed', { error: conversation.connectionError })}
            </div>
          )}
          <ChatArea
            timeline={activeTimeline}
            running={running}
            error={activeSessionId !== null ? (conversation.state.errorBySession[activeSessionId] ?? null) : null}
            progress={activeSessionId !== null ? (conversation.state.progressBySession[activeSessionId] ?? null) : null}
            onOpenInspector={openInspector}
            activePlan={latestPlan === null ? null : { ...latestPlan, showActions: showPlanActions }}
            onBuildPlan={() => {
              if (latestPlan === null) return
              setAgentMode('build')
              void sendTurn('是，实施此计划', 'build', buildImplementPrompt(latestPlan.document))
            }}
            onRevisePlan={(feedback) => {
              setAgentMode('plan')
              const previous = latestPlan?.document
              void sendTurn(
                feedback,
                'plan',
                previous === undefined ? undefined : buildRevisePrompt(previous, feedback)
              )
            }}
            onSkipPlan={() => {
              if (latestPlan !== null) {
                setSkippedPlanIds((current) => ({ ...current, [latestPlan.itemId]: true }))
              }
            }}
          />
          <PromptSuggestions
            items={['Fix the failing test', 'Summarize this repository']}
            visible={!running && activeTimeline.length === 0}
            onPick={(text) => void handleComposerSend(text)}
          />
          {pendingApproval !== null &&
          approvalChannel({
            risk: pendingApproval.riskLevel,
            preset: 'ask',
            action: pendingApproval.action
          }) === 'card' ? (
            <ApprovalCard
              item={{
                requestId: pendingApproval.requestId,
                action: pendingApproval.action,
                risk: pendingApproval.riskLevel
              }}
              onAllow={(requestId) => conversation.resolveApproval(requestId, 'approved')}
              onDeny={(requestId) => conversation.resolveApproval(requestId, 'rejected')}
              onCancel={(requestId) => conversation.dismissApproval(requestId)}
            />
          ) : null}
          <Composer
            disabled={status !== 'running' || activeSessionId === null}
            running={running}
            agentMode={agentMode}
            goal={activeGoal}
            hasPlan={latestPlan !== null && skippedPlanIds[latestPlan.itemId] !== true}
            onSend={(text) => void handleComposerSend(text)}
            onStop={() => void conversation.interrupt()}
            pendingCount={activeSessionId === null ? 0 : (pendingBySession[activeSessionId] ?? []).length}
            steerBlocked={false}
            onSendIntent={(intent, text) => void handleSendIntent(intent, text)}
            onTogglePlanMode={() => {
              const next: AgentRunMode = agentMode === 'plan' ? 'build' : 'plan'
              setAgentMode(next)
              showToast(next === 'plan' ? tr('planModeOn') : tr('planModeOff'))
            }}
            onOpenGoal={openGoalDialog}
            onPickWorkspace={() => void handlePickWorkspaceForChat()}
            models={models.snapshot?.models ?? []}
            modelsLoading={models.loading || (conversation.protocolClient !== null && models.snapshot === null)}
            selectedModelId={selectedTaskModel}
            onSelectModel={(modelId) => {
              if (activeSessionId !== null) {
                const selected = models.snapshot?.models.find((model) => model.id === modelId)
                void conversation.setSessionModel(activeSessionId, modelId, selected?.provider_id ?? null)
              }
            }}
            permissionMode={permissionMode}
            onRequestPermissionModeChange={requestPermissionModeChange}
          />
          </>
          ) : null}
        </main>
        {commandOpen ? (
          <div className="command-palette" data-testid="command-palette" role="dialog">
            <button type="button" className="sheet-backdrop" aria-label={tr('close')} onClick={() => setCommandOpen(false)} />
            <ul className="command-palette-list">
              {DESKTOP_VIEWS.map((view) => (
                <li key={view.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setDesktopView(resolveDesktopView(view.id).id)
                      setCommandOpen(false)
                    }}
                  >
                    {tr(view.titleKey)}
                    <kbd>{view.shortcut}</kbd>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {!inspectorOpen && runPanel?.open === true ? (
          <RunPanel
            model={runPanel.model}
            open={runPanel.open}
            usageAvailable={runPanel.usageAvailable}
            dark={theme === 'dark'}
          />
        ) : null}
        {inspectorOpen && (
          <div className="contextual-inspector-slot">
            <TaskInspector
              focusItem={inspectorItem}
              usage={activeSessionId !== null ? (conversation.state.usageBySession[activeSessionId] ?? EMPTY_USAGE) : EMPTY_USAGE}
              childSessions={activeChildSessions}
              onClose={() => { setInspectorOpen(false); setInspectorItem(null) }}
              onSelectChild={(sessionId) => {
                const child = activeChildSessions.find((entry) => entry.sessionId === sessionId)
                if (child !== undefined) {
                  setInspectorItem({
                    kind: 'child_agent',
                    id: `${activeSessionId ?? 'task'}:child:${child.sessionId}`,
                    sessionId: child.sessionId,
                    agentId: child.agentId,
                    title: `@${child.agentId}`,
                    state: child.state
                  })
                }
              }}
            />
          </div>
        )}
      </div>
      <Statusline
        hasSession={activeSessionId !== null}
        model={selectedTaskModel}
        tokens={
          ((activeSessionId === null
            ? EMPTY_USAGE
            : conversation.state.usageBySession[activeSessionId] ?? EMPTY_USAGE
          ).inputTokens ?? 0) +
          ((activeSessionId === null
            ? EMPTY_USAGE
            : conversation.state.usageBySession[activeSessionId] ?? EMPTY_USAGE
          ).outputTokens ?? 0)
        }
        progress={activeSessionId === null ? undefined : conversation.state.progressBySession[activeSessionId]}
        dark={theme === 'dark'}
      />

      <details className="diagnostics">
        <summary>{tr('diagnostics')}</summary>
        <div className="diagnostics-content">
          <span>appserver: {status}</span>
          <span data-testid="diagnostics-appserver-pid">PID: {info?.appserverPid ?? 'not running'}</span>
          <span data-testid="diagnostics-pending-rpc">pending RPC: {conversation.protocolClient?.pendingRequestCount ?? 0}</span>
          <button type="button" className="appserver-start" onClick={() => platform.start()} disabled={status === 'running' || status === 'starting'}>{tr('start')}</button>
          <button type="button" className="appserver-stop" onClick={() => platform.stop()} disabled={status === 'stopped' || status === 'crashed'}>{tr('stop')}</button>
        </div>
      </details>

      {approvalEnabled && pendingApproval !== null &&
      approvalChannel({
        risk: pendingApproval.riskLevel,
        preset: 'ask',
        action: pendingApproval.action
      }) === 'modal' && (
        <ApprovalModal
          item={pendingApproval}
          onApprove={() => conversation.resolveApproval(pendingApproval.requestId, 'approved')}
          onReject={() => conversation.resolveApproval(pendingApproval.requestId, 'rejected')}
          onAlwaysAllow={(scope, hours) => conversation.saveAlwaysAllowRule(pendingApproval.requestId, scope, hours)}
          onDismiss={() => conversation.dismissApproval(pendingApproval.requestId)}
        />
      )}
      {pendingQuestion !== null && (
        <QuestionModal
          request={pendingQuestion}
          onAnswer={(answer) => conversation.resolveQuestion(pendingQuestion.question_id, { answer })}
          onCancel={() => conversation.resolveQuestion(pendingQuestion.question_id, { cancelled: true })}
        />
      )}
      <ApprovalRulesModal
        open={rulesOpen}
        rules={conversation.approvalRules}
        onClose={() => setRulesOpen(false)}
        onRevoke={conversation.revokeApprovalRule}
      />
      {settingsOpen && (
        <SettingsPage
          appVersion={info?.appVersion ?? ''}
          repoRoot={info?.repoRoot ?? ''}
          savedWorkspaceRoot={workspaceSettings.workspaceRoot}
          effectiveWorkspaceRoot={effectiveWorkspace}
          picking={pickingWorkspace}
          onClose={() => setSettingsOpen(false)}
          onPickWorkspace={() => void pickWorkspace()}
          onClearWorkspace={clearWorkspace}
          onModelSelected={(modelId) => {
            const selected = models.snapshot?.models.find((model) => model.id === modelId)
            if (activeSessionId !== null) {
              void conversation.setSessionModel(activeSessionId, modelId, selected?.provider_id ?? null)
            }
            setSettingsOpen(false)
          }}
          models={models}
          permissionMode={permissionMode}
          onPermissionModeChange={requestPermissionModeChange}
          theme={theme}
          onThemeChange={setTheme}
          language={language}
          onLanguageChange={setLanguage}
          recycleItems={recycleModel.items}
          recycleBlocked={recycleModel.blocked}
          recycleMissing={recycleModel.missing}
          onRestoreDeleted={(sessionId) => void handleRestore(sessionId)}
          onPurgeRecycle={() => void handlePurgeRecycle()}
        />
      )}
      <GoalDialog
        open={goalOpen}
        value={goalDraft}
        onChange={setGoalDraft}
        onClose={() => setGoalOpen(false)}
        onSave={() => {
          if (activeSessionId !== null) persistGoal(activeSessionId, goalDraft)
          setGoalOpen(false)
          showToast(goalDraft.trim() === '' ? tr('goalCleared') : tr('goalSaved'))
        }}
        onClear={() => {
          setGoalDraft('')
          if (activeSessionId !== null) persistGoal(activeSessionId, '')
          setGoalOpen(false)
          showToast(tr('goalCleared'))
        }}
      />
      {pendingFullAuto && (
        <div
          className="confirm-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPendingFullAuto(false)
          }}
        >
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="full-auto-title">
            <h2 id="full-auto-title">{tr('fullAutoTitle')}</h2>
            <p>{tr('fullAutoBody')}</p>
            <div className="confirm-actions">
              <button type="button" onClick={() => setPendingFullAuto(false)}>{tr('cancel')}</button>
              <button type="button" className="danger-action" onClick={() => {
                setPreferences((current) => ({ ...current, permissionMode: 'full_auto' }))
                setPendingFullAuto(false)
              }}>{tr('fullAutoEnable')}</button>
            </div>
          </div>
        </div>
      )}
      {toast !== null && <div className="task-toast" role="status" aria-live="polite" data-testid="task-toast">{toast}</div>}
      {runBanner !== null && (
        <div className="task-toast" role="status" aria-live="polite" data-testid="os-fallback-banner">
          {runBanner.title}: {runBanner.body}
        </div>
      )}
    </div>
    </I18nProvider>
  )
}

export default App
