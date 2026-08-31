import { useEffect, useState } from 'react'
import type { ProtocolClient } from '@rxycode/protocol-client'
import { useI18n } from '../../../i18n/I18nContext.tsx'
import { useDiagnostics, type UpdateStatus } from '../../../platform/index.mts'
import type { UseModelsResult } from '../hooks/useModels'
import type { ModelEntry } from '../hooks/useModels'
import { useCapabilities } from '../hooks/useCapabilities.ts'
import { modelsUnavailableCopy } from '../lib/modelAvailability.mts'
import { groupModelsByProvider } from '../lib/modelPresentation.mts'
import type { DesktopLanguage, PermissionMode, ThemePreference } from '../lib/desktopPreferences.mts'
import {
  effortOptionsFor,
  SETTINGS_SECTIONS,
  type SettingsSectionId
} from '../../../lib/settingsSections.ts'
import { AgentsSettingsPanel } from '../../../features/settings/AgentsSettingsPanel.ts'
import { TeamSection } from '../../../features/settings/TeamSection.ts'
import { TeamInstallPanel } from '../../../features/team/TeamInstallPanel.ts'
import { TeamManager } from '../../../features/team/TeamManager.ts'
import { TeamGallery } from '../../../features/team/TeamGallery.ts'
import { TeamHubNav, type TeamHubTab } from '../../../features/team/TeamHub.ts'
import type { TeamGroup, TeamRecord } from '../../../features/team/team.visual.ts'
import { CapabilityPanel } from '../../../features/capabilities/capabilityPanel.ts'
import type { AgentsSettingsView } from '../../../features/settings/agentsSettings.ts'
import { TrashSection } from '../../../features/settings/TrashSection.ts'
import type { TrashItemModel } from '../../../components/TrashItem.ts'
import { ThemeMenu } from '../../../features/composer/ThemeMenu.ts'

export type SettingsTab = SettingsSectionId

export interface SettingsPageProps {
  appVersion: string
  repoRoot: string
  savedWorkspaceRoot: string | null
  effectiveWorkspaceRoot: string
  picking: boolean
  onClose: () => void
  onPickWorkspace: () => void
  onClearWorkspace: () => void
  onModelSelected?: (modelId: string) => void
  models: UseModelsResult
  permissionMode: PermissionMode
  onPermissionModeChange: (mode: PermissionMode) => void
  theme: ThemePreference
  onThemeChange: (theme: ThemePreference) => void
  language: DesktopLanguage
  onLanguageChange: (language: DesktopLanguage) => void
  recycleItems: readonly TrashItemModel[]
  recycleBlocked: boolean
  recycleMissing: readonly string[]
  onRestoreDeleted: (sessionId: string) => void
  onPurgeItem?: (sessionId: string) => void
  onPurgeRecycle: () => void
  teams?: readonly TeamRecord[]
  groups?: readonly TeamGroup[]
  teamLoading?: boolean
  teamError?: string | null
  agentsSettings?: AgentsSettingsView | null
  onAgentsSettingsChange?: (next: AgentsSettingsView) => void
  onRenameGroup?: (id: string, name: string) => void
  onDeleteGroup?: (id: string) => void
  onActivateTeam?: (teamId: string) => void
  onActivateGroup?: (groupId: string) => void
  onCreateTeam?: () => void
  onPreviewInstall?: (source: string, value: string) => void
  onInstallTeam?: (input: { groupId: string; source: string; value: string }) => void
  installPreview?: { message?: string; hooks?: boolean; members?: number } | null
  protocolClient?: ProtocolClient | null
  activeTeamId?: string | null
}



const UPDATE_STATUS_KEYS: Record<UpdateStatus, string> = {
  disabled: 'updateDisabled',
  idle: 'updateIdle',
  checking: 'updateChecking',
  available: 'updateAvailable',
  'not-available': 'updateNotAvailable',
  downloading: 'updateDownloading',
  downloaded: 'updateDownloaded',
  error: 'updateError'
}

function UnavailablePanel({
  title,
  detail,
  blockedPrerequisite
}: {
  title: string
  detail: string
  blockedPrerequisite: boolean
}): React.JSX.Element {
  const { t } = useI18n()
  return (
    <div className="blocked-panel">
      {blockedPrerequisite ? <span className="blocked-badge">{t('blocked')}</span> : null}
      <p className="blocked-title">{title}</p>
      <p className="blocked-detail">{detail}</p>
    </div>
  )
}

function ApiKeyRow({
  modelId,
  modelName,
  onSave,
  onDelete
}: {
  modelId: string
  modelName: string
  onSave: (key: string) => void
  onDelete: () => void
}): React.JSX.Element {
  const [key, setKey] = useState('')
  const [saved, setSaved] = useState(false)

  const { t } = useI18n()
  const submit = (): void => {
    if (key.trim() === '') return
    onSave(key.trim())
    setKey('')
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="apikey-row">
      <span className="apikey-model">{modelName}</span>
      <span className="apikey-id">{modelId}</span>
      <input
        type="password"
        className="apikey-input"
        placeholder={t('apiKeyPlaceholder')}
        value={key}
        onChange={(event) => setKey(event.target.value)}
      />
      <button type="button" className="apikey-save" disabled={key.trim() === ''} onClick={submit}>
        {t('save')}
      </button>
      <button type="button" className="apikey-delete" onClick={onDelete}>
        {t('clear')}
      </button>
      {saved && <span className="apikey-saved">{t('apiKeySaved')}</span>}
    </div>
  )
}

function AddModelPanel({ models, onModelSelected }: { models: UseModelsResult; onModelSelected?: (modelId: string) => void }): React.JSX.Element {
  const { t } = useI18n()
  const [presets, setPresets] = useState<Array<{ id: string; name: string; base_url: string; category?: string }>>([])
  const [selectedPreset, setSelectedPreset] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [discovered, setDiscovered] = useState<Array<{ id: string }>>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const loadPresets = async (): Promise<void> => {
    const items = await models.listPresets()
    setPresets(items)
    if (items.length > 0) {
      setSelectedPreset(items[0].id)
      setBaseUrl(items[0].base_url)
    }
  }

  useEffect(() => {
    void loadPresets()
  }, [])

  const applyPreset = (presetId: string): void => {
    setSelectedPreset(presetId)
    const preset = presets.find((p) => p.id === presetId)
    if (preset) setBaseUrl(preset.base_url)
  }

  const runDiscover = async (): Promise<void> => {
    if (apiKey.trim() === '' || baseUrl.trim() === '') {
      setNotice('请先填写 API Key 与 Base URL')
      return
    }
    setBusy(true)
    setNotice(null)
    try {
      const found = await models.discover(apiKey.trim(), baseUrl.trim())
      if (found.length === 0) {
        setNotice('未发现模型，请检查凭据与地址')
        setDiscovered([])
      } else {
        setDiscovered(found)
        setSelected(Object.fromEntries(found.map((m) => [m.id, true])))
        setNotice(`发现 ${found.length} 个模型`)
      }
    } finally {
      setBusy(false)
    }
  }

  const submitOnboard = async (): Promise<void> => {
    if (discovered.length === 0) {
      setNotice('请先探测模型')
      return
    }
    const ids = discovered.filter((m) => selected[m.id]).map((m) => m.id)
    if (ids.length === 0) {
      setNotice('请至少勾选一个模型')
      return
    }
    setBusy(true)
    setNotice(null)
    try {
      if (ids.length === 1) {
        const result = await models.onboard({
          providerModelId: ids[0],
          apiKey: apiKey.trim(),
          baseUrl: baseUrl.trim()
        })
        if (result.ok && result.id !== undefined) {
          await models.setActive(result.id)
          onModelSelected?.(result.id)
        }
        setNotice(result.ok ? `已添加 ${ids[0]}` : result.message ?? '添加失败')
      } else {
        const result = await models.onboardBatch({
          apiKey: apiKey.trim(),
          baseUrl: baseUrl.trim(),
          modelIds: ids
        })
        if (result.ok) {
          const selectedModelId = result.active ?? result.onboarded?.[0] ?? result.added?.[0]
          if (selectedModelId !== undefined) {
            await models.setActive(selectedModelId)
            onModelSelected?.(selectedModelId)
          }
          const failed = result.failed ?? []
          setNotice(failed.length > 0 ? `已添加 ${ids.length - failed.length} 个，失败 ${failed.length} 个` : `已添加 ${ids.length} 个模型`)
        } else {
          setNotice(result.message ?? '批量添加失败')
        }
      }
      setDiscovered([])
      setSelected({})
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="addmodel-card">
      <div className="addmodel-title">{t('addModel')}</div>
      <div className="addmodel-row">
        <span className="label">{t('providerPreset')}</span>
        <ThemeMenu
          value={selectedPreset}
          options={[
            { value: '', label: t('selectPreset') },
            ...presets.map((preset) => ({ value: preset.id, label: preset.name }))
          ]}
          onChange={(value) => applyPreset(value)}
          testId="addmodel-preset"
          ariaLabel={t('providerPreset')}
          placement="down"
        />
      </div>
      <div className="addmodel-row">
        <span className="label">{t('baseUrl')}</span>
        <input
          className="addmodel-input"
          type="text"
          placeholder="https://api.example.com/v1"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
      </div>
      <div className="addmodel-row">
        <span className="label">{t('apiKey')}</span>
        <input
          className="addmodel-input"
          type="password"
          placeholder={t('apiKeyPlaceholder')}
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />
      </div>
      <div className="addmodel-actions">
        <button
          type="button"
          className="addmodel-discover"
          disabled={busy || apiKey.trim() === '' || baseUrl.trim() === ''}
          onClick={() => void runDiscover()}
        >
          探测模型
        </button>
        {discovered.length > 0 && (
          <button
            type="button"
            className="addmodel-onboard"
            disabled={busy}
            onClick={() => void submitOnboard()}
          >
            添加勾选模型
          </button>
        )}
      </div>
      {discovered.length > 0 && (
        <div className="addmodel-discovered">
          {discovered.map((model) => (
            <label key={model.id} className="addmodel-check">
              <input
                type="checkbox"
                checked={selected[model.id] === true}
                onChange={(event) =>
                  setSelected((prev) => ({ ...prev, [model.id]: event.target.checked }))
                }
              />
              {model.id}
            </label>
          ))}
        </div>
      )}
      {notice !== null && <p className="addmodel-notice">{notice}</p>}
    </div>
  )
}

function SettingsPage(props: SettingsPageProps): React.JSX.Element {
  const { t } = useI18n()
  const [tab, setTab] = useState<SettingsSectionId>('general')
  const [teamHub, setTeamHub] = useState<TeamHubTab>('gallery')
  const [teamAuto, setTeamAuto] = useState(false)
  const skillCaps = useCapabilities(props.protocolClient ?? null, 'skill')
  const mcpCaps = useCapabilities(props.protocolClient ?? null, 'mcp')
  const activeModel = props.models.snapshot?.models.find((model) => model.active) ?? null
  const effortOptions = effortOptionsFor(activeModel)
  const diagnostics = useDiagnostics()
  const updateStatus = diagnostics.updateStatus?.status ?? null

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        props.onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [props.onClose])

  return (
    <div className="settings-overlay" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) props.onClose()
    }}>
      <div className="settings-page" role="dialog" aria-modal="true" aria-labelledby="settings-title" data-testid="settings-dialog">
        <header className="settings-header">
          <div id="settings-title" className="settings-title">{t('settings')}</div>
          <button type="button" className="settings-close" data-testid="close-settings" onClick={props.onClose}>
            {t('close')}
          </button>
        </header>
        <div className="settings-body">
        <nav className="settings-tabs" data-testid="settings-nav">
          {SETTINGS_SECTIONS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`settings-tab${tab === entry.id ? ' active' : ''}`}
              data-tab={entry.id === 'models' ? 'model' : entry.id}
              onClick={() => setTab(entry.id)}
            >
              {t(entry.labelKey)}
            </button>
          ))}
        </nav>
        <div className="settings-content">
          {tab === 'recycle' && (
            <section className="settings-panel" data-testid="settings-recycle">
              <TrashSection
                items={props.recycleItems}
                blocked={props.recycleBlocked}
                missing={props.recycleMissing}
                locale={props.language}
                onRestore={props.onRestoreDeleted}
                onPurgeItem={props.onPurgeItem}
                onPurgeConfirmed={props.onPurgeRecycle}
              />
            </section>
          )}
          {tab === 'general' && (
            <section className="settings-panel" data-testid="general-settings">
              <h2>{t('general')}</h2>
              <div className="settings-option-row">
                <div><strong>{t('approvalMode')}</strong><p className="settings-hint">{t('approvalModeHint')}</p></div>
                <ThemeMenu
                  value={props.permissionMode}
                  options={[
                    { value: 'confirm_all', label: t('modeConfirmAll') },
                    { value: 'auto_edit', label: t('modeAutoEdit') },
                    { value: 'full_auto', label: t('modeFullAuto') }
                  ]}
                  onChange={(value) => props.onPermissionModeChange(value as PermissionMode)}
                  testId="settings-permission-mode"
                  ariaLabel={t('approvalMode')}
                  placement="down"
                  align="end"
                />
              </div>
              <div className="settings-option-row">
                <div><strong>{t('language')}</strong><p className="settings-hint">{t('languageHint')}</p></div>
                <ThemeMenu
                  value={props.language}
                  options={[
                    { value: 'zh-CN', label: t('languageZh') },
                    { value: 'en-US', label: t('languageEn') }
                  ]}
                  onChange={(value) => props.onLanguageChange(value as DesktopLanguage)}
                  testId="settings-language"
                  ariaLabel={t('language')}
                  placement="down"
                  align="end"
                />
              </div>
            </section>
          )}
          {tab === 'appearance' && (
            <section className="settings-panel" data-testid="settings-appearance">
              <h2>{t('appearance')}</h2>
              <div className="settings-option-row">
                <div><strong>{t('theme')}</strong><p className="settings-hint">{t('themeHint')}</p></div>
                <ThemeMenu
                  value={props.theme}
                  options={[
                    { value: 'system', label: t('themeSystem') },
                    { value: 'light', label: t('themeLight') },
                    { value: 'dark', label: t('themeDark') },
                    { value: 'high-contrast', label: t('themeHighContrast') }
                  ]}
                  onChange={(value) => props.onThemeChange(value as ThemePreference)}
                  testId="settings-theme"
                  ariaLabel={t('theme')}
                  placement="down"
                  align="end"
                />
              </div>
            </section>
          )}
          {tab === 'models' && (
            <section className="settings-panel">
              <h2>{t('models')}</h2>
              {props.models.loading && !props.models.supported ? (
                <p className="settings-hint">{t('loading')}</p>
              ) : !props.models.supported ? (
                <>
                  <UnavailablePanel
                    {...modelsUnavailableCopy(
                      props.models.unavailableReason ?? 'error',
                      props.models.error,
                      'models'
                    )}
                  />
                  {props.models.unavailableReason === 'method-not-found' ? (
                    <UnavailablePanel
                      title="Phase 3 上限来源摘要"
                      detail="resolved_max_tokens / limit_source / context_window 由后端 models/list 提供；旧版 appserver 无此字段时此处不可用。"
                      blockedPrerequisite
                    />
                  ) : null}
                </>
              ) : (
                <div className="models-list">
                  {props.models.loading && <p className="settings-hint">{t('loading')}</p>}
                  {props.models.error !== null && (
                    <p className="settings-error">{props.models.error}</p>
                  )}
                  {(props.models.snapshot?.models ?? []).length === 0 && (
                    <p className="settings-hint">{t('noModels')}</p>
                  )}
                  {groupModelsByProvider(props.models.snapshot?.models ?? []).map(([group, entries]) => (
                    <section key={group} className="model-group" aria-labelledby={`model-group-${group}`}>
                      <h3 id={`model-group-${group}`} className="model-group-title">{group}</h3>
                      {entries.map((model: ModelEntry) => (
                        <div key={model.id} className={`model-row${model.active ? ' active' : ''}`} data-testid="model-row" data-model-id={model.id}>
                          <div className="model-main">
                            <span className="model-name">{model.nickname || model.name}</span>
                            <span className="model-id">{model.id}</span>
                            <span className="model-provider">{model.provider_name}</span>
                            {model.active && <span className="model-badge">{t('current')}</span>}
                            {model.limit_source !== undefined && (
                              <span className="model-limit">
                                max_out={model.resolved_max_tokens ?? 'auto'} · {model.limit_source}
                                {model.warning ? ` · ${model.warning}` : ''}
                              </span>
                            )}
                          </div>
                          <div className="model-actions">
                            {!model.active && (
                              <button
                                type="button"
                                className="model-activate"
                                data-testid="model-activate"
                                onClick={() => void props.models.setActive(model.id).then((ok) => {
                                  if (ok) props.onModelSelected?.(model.id)
                                })}
                              >
                                {t('setCurrent')}
                              </button>
                            )}
                            <button
                              type="button"
                              className="model-test"
                              onClick={() => void props.models.testConnection(model.id)}
                            >
                              {t('testConnection')}
                            </button>
                            <button
                              type="button"
                              className="model-remove"
                              onClick={() => void props.models.remove(model.id)}
                            >
                               {t('remove')}
                            </button>
                          </div>
                        </div>
                      ))}
                    </section>
                  ))}
                </div>
              )}
              <div className="settings-option-row">
                <div><strong>{t('effort')}</strong></div>
                <ThemeMenu
                  value={
                    effortOptions.includes(props.models.snapshot?.effort ?? '')
                      ? (props.models.snapshot?.effort ?? '')
                      : ''
                  }
                  options={
                    effortOptions.length === 0
                      ? [{ value: '', label: t('effortNone') }]
                      : effortOptions.map((option) => ({ value: option, label: option }))
                  }
                  onChange={(value) => {
                    const id = props.models.snapshot?.active
                    if (id === undefined || id === '') return
                    void props.models.setActive(id, value)
                  }}
                  disabled={effortOptions.length === 0 || activeModel === null}
                  testId="effort-select"
                  ariaLabel={t('effort')}
                  placement="down"
                  align="end"
                />
              </div>
            </section>
          )}
          {tab === 'addModel' && (
            <section className="settings-panel" data-testid="settings-add-model">
              <h2>{t('addModel')}</h2>
              {props.models.supported && <AddModelPanel models={props.models} onModelSelected={props.onModelSelected} />}
              <h3>{t('apiKey')}</h3>
              {props.models.loading && !props.models.supported ? (
                <p className="settings-hint">{t('loading')}</p>
              ) : !props.models.supported ? (
                <UnavailablePanel
                  {...modelsUnavailableCopy(
                    props.models.unavailableReason ?? 'error',
                    props.models.error,
                    'credentials'
                  )}
                />
              ) : (
                <div className="apikey-list">
                  {(props.models.snapshot?.models ?? []).length === 0 && (
                    <p className="settings-hint">{t('noModelsForKeys')}</p>
                  )}
                  {(props.models.snapshot?.models ?? []).map((model: ModelEntry) => (
                    <ApiKeyRow
                      key={model.id}
                      modelId={model.id}
                      modelName={model.nickname || model.name}
                      onSave={(key) => void props.models.upsertCredential(model.id, key)}
                      onDelete={() => void props.models.deleteCredential(model.id)}
                    />
                  ))}
                </div>
              )}
            </section>
          )}
          {tab === 'general' && (
            <section className="settings-panel">
              <h2>{t('workspace')}</h2>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">{t('workspaceEffective')}</span>
                  <span className="workspace-path">{props.effectiveWorkspaceRoot}</span>
                </div>
                <div className="workspace-row">
                  <span className="label">{t('workspaceSaved')}</span>
                  <span className="workspace-path">
                    {props.savedWorkspaceRoot ?? t('workspaceUnset')}
                  </span>
                </div>
                <div className="workspace-actions">
                  <button
                    type="button"
                    className="workspace-pick"
                    disabled={props.picking}
                    onClick={() => void props.onPickWorkspace()}
                  >
                    {props.picking ? t('picking') : t('pickDirectory')}
                  </button>
                  <button
                    type="button"
                    className="workspace-clear"
                    disabled={props.savedWorkspaceRoot === null || props.picking}
                    onClick={props.onClearWorkspace}
                  >
                    {t('restoreDefault')}
                  </button>
                </div>
                <p className="settings-hint">
                  {t('workspaceHint')}
                </p>
              </div>
            </section>
          )}
          {tab === 'general' && (
            <section className="settings-panel">
              <h2>{t('updatesDiagnostics')}</h2>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">{t('currentVersion')}</span>
                  <span className="workspace-path">{props.appVersion}</span>
                </div>
                <div className="workspace-row">
                  <span className="label">{t('updateStatus')}</span>
                  <span className="workspace-path">
                    {updateStatus !== null ? t(UPDATE_STATUS_KEYS[updateStatus]) : t('loading')}
                  </span>
                </div>
                {diagnostics.updateStatus?.error !== null &&
                  diagnostics.updateStatus?.error !== undefined && (
                    <p className="settings-hint">错误：{diagnostics.updateStatus.error}</p>
                  )}
                {diagnostics.updateStatus?.progress !== null &&
                  diagnostics.updateStatus?.progress !== undefined && (
                    <p className="settings-hint">
                      下载进度：{diagnostics.updateStatus.progress.percent.toFixed(1)}%
                    </p>
                  )}
                <div className="workspace-actions">
                  <button
                    type="button"
                    className="workspace-pick"
                    disabled={
                      updateStatus === 'checking' ||
                      updateStatus === 'downloading' ||
                      diagnostics.updateStatus === null
                    }
                    onClick={() => void diagnostics.checkForUpdates()}
                  >
                    {t('checkUpdates')}
                  </button>
                  {updateStatus === 'available' && (
                    <button
                      type="button"
                      className="workspace-pick"
                      onClick={() => void diagnostics.downloadUpdate()}
                    >
                      {t('downloadUpdate')}
                    </button>
                  )}
                  {updateStatus === 'downloaded' && (
                    <button
                      type="button"
                      className="workspace-pick"
                      onClick={() => diagnostics.installUpdate()}
                    >
                      {t('installUpdate')}
                    </button>
                  )}
                </div>
                <p className="settings-hint">
                  更新为手动触发：检查、下载、安装均由你点击执行，启动时不会强制检查；检查或下载失败不会影响当前版本运行。
                </p>
              </div>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">{t('crashReport')}</span>
                  <label className="settings-toggle">
                    <input
                      type="checkbox"
                      checked={diagnostics.consent === true}
                      disabled={diagnostics.consent === null}
                      onChange={(event) => void diagnostics.setConsent(event.target.checked)}
                    />
                    {t('crashConsent')}
                  </label>
                </div>
                <p className="settings-hint">
                  诊断包只包含版本、平台、协议状态与日志摘要，不含 API Key、代码、完整 prompt
                  或工具输入输出。未开启同意时仅在本地记录。
                </p>
                <h3>{t('recentDiagnostics')}</h3>
                {diagnostics.reports.length === 0 ? (
                  <p className="settings-hint">{t('noDiagnostics')}</p>
                ) : (
                  <ul className="crash-report-list">
                    {diagnostics.reports.map((report) => (
                      <li key={report.id}>
                        {report.capturedAt} · {report.source}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          )}
          {tab === 'skills' && (
            <section className="settings-panel" data-testid="settings-skills">
              <h2>{t('skills')}</h2>
              <CapabilityPanel
                kind="skill"
                items={skillCaps.items}
                loading={skillCaps.loading}
                error={skillCaps.error}
                labels={{
                  empty: t('capabilitiesEmpty'),
                  enabled: t('capabilityEnabled'),
                  installed: t('capabilityInstalled'),
                  available: t('capabilityAvailable'),
                  connection: t('capabilityConnection')
                }}
                onSetEnabled={(id, enabled) => void skillCaps.setEnabled(id, enabled)}
              />
            </section>
          )}
          {tab === 'mcp' && (
            <section className="settings-panel" data-testid="settings-mcp">
              <h2>{t('mcp')}</h2>
              <CapabilityPanel
                kind="mcp"
                items={mcpCaps.items}
                loading={mcpCaps.loading}
                error={mcpCaps.error}
                labels={{
                  empty: t('capabilitiesEmpty'),
                  enabled: t('capabilityEnabled'),
                  installed: t('capabilityInstalled'),
                  available: t('capabilityAvailable'),
                  connection: t('capabilityConnection')
                }}
                onSetEnabled={(id, enabled) => void mcpCaps.setEnabled(id, enabled)}
              />
            </section>
          )}
          {tab === 'team' && (
            <section className="settings-panel" data-testid="settings-team">
              <h2>{t('team')}</h2>
              <TeamHubNav
                tab={teamHub}
                labels={{
                  gallery: t('teamHubGallery'),
                  create: t('teamHubCreate'),
                  settings: t('teamHubSettings')
                }}
                onChange={setTeamHub}
              />
              {teamHub === 'gallery' ? (
                <TeamGallery
                  groups={props.groups ?? []}
                  teams={props.teams ?? []}
                  loading={props.teamLoading}
                  error={props.teamError}
                  activeTeamId={props.activeTeamId}
                  labels={{
                    search: t('searchSpecialists'),
                    featured: t('featuredScenarios'),
                    specialists: t('specialists'),
                    all: t('allCategories'),
                    use: t('useTeam'),
                    intro: t('teamIntro'),
                    scope: t('teamScope'),
                    ability: t('teamAbility'),
                    domains: t('teamDomains'),
                    members: t('teamMembers'),
                    leader: t('teamLeader'),
                    tryAsk: t('tryAskMe'),
                    summonNamed: t('summonNamed')
                  }}
                  onUse={(teamId) => props.onActivateTeam?.(teamId)}
                />
              ) : null}
              {teamHub === 'create' ? (
                <>
                  <button
                    type="button"
                    className="team-hub-create-chat"
                    data-testid="team-hub-create-chat"
                    onClick={() => props.onCreateTeam?.()}
                  >
                    {t('createTeam')}
                  </button>
                  <p className="settings-hint">{t('createTeamHint')}</p>
                  <TeamInstallPanel
                    groups={props.groups ?? []}
                    preview={props.installPreview}
                    labels={{
                      source: t('teamImportSource'),
                      directory: t('teamImportDirectory'),
                      zip: t('teamImportZip'),
                      github: t('teamImportGithub'),
                      confirm: t('teamInstallConfirm'),
                      finish: t('teamInstallFinish')
                    }}
                    onPreview={props.onPreviewInstall}
                    onInstall={(input) => props.onInstallTeam?.(input)}
                  />
                </>
              ) : null}
              {teamHub === 'settings' ? (
                <>
                  {props.agentsSettings != null && props.onAgentsSettingsChange != null ? (
                    <AgentsSettingsPanel
                      settings={props.agentsSettings}
                      models={(props.models.snapshot?.models ?? []).map((model) => ({
                        id: model.id,
                        label: model.nickname || model.name || model.id
                      }))}
                      roles={[...new Set((props.teams ?? []).flatMap((team) => (team.members ?? []).map((member) => member.role)))]}
                      labels={{
                        agentsEnable: t('agentsEnable'),
                        agentsRoute: t('agentsRoute'),
                        agentsRouterModel: t('agentsRouterModel'),
                        agentsBudget: t('agentsBudget'),
                        multiModelEnable: t('multiModelEnable'),
                        masterModel: t('masterModel'),
                        inheritMaster: t('inheritMaster'),
                        routeAuto: t('routeAuto'),
                        routeSolo: t('routeSolo'),
                        routeTeam: t('routeTeam'),
                        routerNone: t('routerNone')
                      }}
                      onChange={props.onAgentsSettingsChange}
                    />
                  ) : null}
                  <TeamSection auto={teamAuto} onAutoChange={setTeamAuto} />
                  <TeamManager
                    groups={props.groups ?? []}
                    loading={props.teamLoading}
                    error={props.teamError}
                    onRename={(id, name) => props.onRenameGroup?.(id, name)}
                    onDelete={(id) => props.onDeleteGroup?.(id)}
                    onInstall={() => undefined}
                    onActivate={(id) => props.onActivateGroup?.(id)}
                  />
                </>
              ) : null}
            </section>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
