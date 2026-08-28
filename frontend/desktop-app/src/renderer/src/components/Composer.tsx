import { ArrowUp, ChevronDown, Mic, Plus, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import type { ModelEntry } from '../hooks/useModels'
import { groupModelsByProvider } from '../lib/modelPresentation.mts'
import type { PermissionMode } from '../lib/desktopPreferences.mts'
import type { AgentRunMode } from '../lib/planDocument.mts'
import { canSubmitComposer, promptWithAttachment, shouldSubmitOnKey } from '../lib/composerBehavior.mts'
import { SendDropdown } from '../../../features/composer/SendDropdown.ts'
import type { SendIntent } from '../../../features/composer/pending.queue.ts'
import ComposerPlusMenu from './ComposerPlusMenu'

interface ComposerProps {
  disabled: boolean
  running: boolean
  agentMode: AgentRunMode
  goal: string
  hasPlan: boolean
  onSend: (text: string) => void
  onStop: () => void
  onTogglePlanMode: () => void
  onOpenGoal: () => void
  onPickWorkspace: () => void
  models: ModelEntry[]
  modelsLoading?: boolean
  selectedModelId: string
  onSelectModel: (modelId: string) => void
  permissionMode: PermissionMode
  onRequestPermissionModeChange: (mode: PermissionMode) => void
  pendingCount?: number
  steerBlocked?: boolean
  onSendIntent?: (intent: SendIntent, text: string) => void
}

const MODE_KEYS: Record<PermissionMode, string> = {
  confirm_all: 'modeConfirmAll',
  auto_edit: 'modeAutoEdit',
  full_auto: 'modeFullAuto'
}

type FileWithPath = File & { path?: string }

function attachmentFromFile(file: File): { name: string; path: string } {
  const path = typeof (file as FileWithPath).path === 'string' && (file as FileWithPath).path !== ''
    ? (file as FileWithPath).path as string
    : file.name
  return { name: file.name, path }
}

function Composer({
  disabled,
  running,
  agentMode,
  goal,
  hasPlan,
  onSend,
  onStop,
  onTogglePlanMode,
  onOpenGoal,
  onPickWorkspace,
  models,
  modelsLoading = false,
  selectedModelId,
  onSelectModel,
  permissionMode,
  onRequestPermissionModeChange,
  pendingCount = 0,
  steerBlocked = false,
  onSendIntent
}: ComposerProps): React.JSX.Element {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [attachment, setAttachment] = useState<{ name: string; path: string } | null>(null)
  const [plusOpen, setPlusOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const plusRef = useRef<HTMLDivElement | null>(null)
  const canSend = canSubmitComposer({ disabled, running, text, hasAttachment: attachment !== null })
  const groups = groupModelsByProvider(models)
  const planMode = agentMode === 'plan'

  const submit = (): void => {
    if (!canSend) return
    onSend(promptWithAttachment(text, attachment))
    setText('')
    setAttachment(null)
  }

  useEffect(() => {
    if (!plusOpen) return
    const onPointer = (event: MouseEvent): void => {
      if (plusRef.current !== null && !plusRef.current.contains(event.target as Node)) {
        setPlusOpen(false)
      }
    }
    window.addEventListener('mousedown', onPointer)
    return () => window.removeEventListener('mousedown', onPointer)
  }, [plusOpen])

  const placeholder = disabled
    ? t('composerWaiting')
    : running
      ? t('composerRunning')
      : planMode
        ? (hasPlan ? t('composerPlanRevise') : t('composerPlanNew'))
        : t('composerIdle')

  return (
    <footer className="composer" data-testid="composer">
      <form className="composer-surface" data-testid="composer-surface" onSubmit={(event) => { event.preventDefault(); submit() }}>
        {attachment !== null && (
          <div className="composer-attachment" data-testid="composer-attachment">
            <span title={attachment.path}>{attachment.name}</span>
            <button
              type="button"
              className="composer-attachment-remove"
              aria-label={t('removeAttachment')}
              onClick={() => setAttachment(null)}
            >
              ×
            </button>
          </div>
        )}
        {goal !== '' && (
          <button type="button" className="composer-goal-chip" data-testid="composer-goal-chip" onClick={onOpenGoal}>
            {t('goal')} · {goal}
          </button>
        )}
        <textarea
          aria-label={t('task')}
          data-testid="composer-input"
          value={text}
          placeholder={placeholder}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && plusOpen) {
              event.preventDefault()
              setPlusOpen(false)
            } else if (event.key === 'Escape' && running) {
              event.preventDefault()
              onStop()
            } else if (shouldSubmitOnKey({ key: event.key, shiftKey: event.shiftKey, running })) {
              event.preventDefault()
              submit()
            }
          }}
          rows={1}
          disabled={disabled}
        />
        <input
          ref={fileInputRef}
          type="file"
          className="composer-file-input"
          aria-hidden="true"
          tabIndex={-1}
          onChange={(event) => {
            const file = event.target.files?.[0]
            setAttachment(file === undefined ? null : attachmentFromFile(file))
            event.target.value = ''
          }}
        />
        <div className="composer-toolbar">
          <div className="composer-toolbar-left">
            <div className="composer-plus" ref={plusRef}>
              <button
                type="button"
                className={'composer-icon-button' + (plusOpen ? ' is-open' : '')}
                aria-label={t('composerAdd')}
                aria-expanded={plusOpen}
                data-testid="composer-plus"
                title={t('composerAdd')}
                onClick={() => setPlusOpen((open) => !open)}
                disabled={disabled || running}
              >
                <Plus aria-hidden="true" size={18} />
              </button>
              <ComposerPlusMenu
                open={plusOpen}
                planMode={planMode}
                onClose={() => setPlusOpen(false)}
                onAttachFile={() => fileInputRef.current?.click()}
                onPickWorkspace={onPickWorkspace}
                onOpenGoal={onOpenGoal}
                onTogglePlanMode={onTogglePlanMode}
              />
            </div>
            {planMode && (
              <button
                type="button"
                className="composer-mode-chip"
                data-testid="composer-plan-chip"
                title={t('planModeOff')}
                onClick={onTogglePlanMode}
              >
                {t('planMode')}
              </button>
            )}
            <label className="composer-permission-control">
              <span className="sr-only">{t('permissionMode')}</span>
              <select
                aria-label={t('permissionMode')}
                data-testid="composer-permission-mode"
                value={permissionMode}
                disabled={disabled || running}
                onChange={(event) => onRequestPermissionModeChange(event.target.value as PermissionMode)}
              >
                {(Object.keys(MODE_KEYS) as PermissionMode[]).map((mode) => (
                  <option key={mode} value={mode}>{t(MODE_KEYS[mode])}</option>
                ))}
              </select>
              <ChevronDown aria-hidden="true" size={13} />
            </label>
          </div>
          <div className="composer-toolbar-right">
            <label className="composer-model-control">
              <span className="sr-only">{t('taskModel')}</span>
              <select
                id="composer-model"
                aria-label={t('taskModel')}
                data-testid="composer-model"
                value={selectedModelId}
                disabled={disabled || running || models.length === 0}
                onChange={(event) => onSelectModel(event.target.value)}
              >
                {models.length === 0 ? (
                  <option value="">{modelsLoading ? t('loadingModels') : t('noConfiguredModels')}</option>
                ) : (
                  groups.map(([group, entries]) => (
                    <optgroup key={group} label={group}>
                      {entries.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.nickname || model.name || model.provider_model_id}
                        </option>
                      ))}
                    </optgroup>
                  ))
                )}
              </select>
              <ChevronDown aria-hidden="true" size={13} />
            </label>
            <button
              type="button"
              className="composer-icon-button composer-mic"
              aria-label={t('voiceUnavailable')}
              title={t('voiceUnavailable')}
              disabled
            >
              <Mic aria-hidden="true" size={16} />
            </button>
            {running && onSendIntent !== undefined ? (
              <SendDropdown
                running
                pendingCount={pendingCount}
                steerBlocked={steerBlocked}
                onSend={(intent) => {
                  const payload = promptWithAttachment(text, attachment)
                  onSendIntent(intent, payload)
                  if (intent !== 'queue' || payload.trim() !== '') {
                    setText('')
                    setAttachment(null)
                  }
                }}
              />
            ) : null}
            <button
              type={running ? 'button' : 'submit'}
              className={running ? 'composer-send composer-stop stop' : 'composer-send send'}
              data-testid={running ? 'composer-stop' : 'composer-send'}
              aria-label={running ? t('stopTask') : t('sendTask')}
              onClick={running ? onStop : undefined}
              disabled={!running && !canSend}
            >
              {running ? <Square aria-hidden="true" size={14} fill="currentColor" /> : <ArrowUp aria-hidden="true" size={19} />}
            </button>
          </div>
        </div>
      </form>
    </footer>
  )
}

export default Composer
