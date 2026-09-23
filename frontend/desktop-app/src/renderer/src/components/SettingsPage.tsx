import { useEffect, useState } from 'react'
import { useDiagnostics, type UpdateStatus } from '../../../platform/index.mts'
import type { UseModelsResult } from '../hooks/useModels'
import type { ModelEntry } from '../hooks/useModels'
import { modelsUnavailableCopy } from '../lib/modelAvailability.mts'
import { groupModelsByProvider } from '../lib/modelPresentation.mts'
import type { DesktopLanguage, PermissionMode, ThemePreference } from '../lib/desktopPreferences.mts'

export type SettingsTab = 'general' | 'model' | 'apikey' | 'workspace' | 'diagnostics'

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
}

const TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: 'general', label: 'General' },
  { id: 'model', label: '模型' },
  { id: 'apikey', label: 'API Key' },
  { id: 'workspace', label: '工作区' },
  { id: 'diagnostics', label: '更新与诊断' }
]

const UPDATE_STATUS_LABELS: Record<UpdateStatus, string> = {
  disabled: '不可用',
  idle: '空闲',
  checking: '检查中…',
  available: '有可用更新',
  'not-available': '已是最新',
  downloading: '下载中…',
  downloaded: '已下载，可安装',
  error: '出错'
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
  return (
    <div className="blocked-panel">
      {blockedPrerequisite ? <span className="blocked-badge">BLOCKED_PREREQUISITE</span> : null}
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
        placeholder="粘贴 API Key（不回显）"
        value={key}
        onChange={(event) => setKey(event.target.value)}
      />
      <button type="button" className="apikey-save" disabled={key.trim() === ''} onClick={submit}>
        保存
      </button>
      <button type="button" className="apikey-delete" onClick={onDelete}>
        清除
      </button>
      {saved && <span className="apikey-saved">已保存（后端加密存储）</span>}
    </div>
  )
}

function AddModelPanel({ models, onModelSelected }: { models: UseModelsResult; onModelSelected?: (modelId: string) => void }): React.JSX.Element {
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
      <div className="addmodel-title">添加模型</div>
      <div className="addmodel-row">
        <span className="label">Provider 预设</span>
        <select
          className="addmodel-select"
          value={selectedPreset}
          onChange={(event) => applyPreset(event.target.value)}
          onFocus={() => void loadPresets()}
        >
          <option value="">（选择预设）</option>
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.name}
            </option>
          ))}
        </select>
      </div>
      <div className="addmodel-row">
        <span className="label">Base URL</span>
        <input
          className="addmodel-input"
          type="text"
          placeholder="https://api.example.com/v1"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
      </div>
      <div className="addmodel-row">
        <span className="label">API Key</span>
        <input
          className="addmodel-input"
          type="password"
          placeholder="粘贴 API Key（不回显）"
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
  const [tab, setTab] = useState<SettingsTab>('general')
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
          <div id="settings-title" className="settings-title">Settings</div>
          <button type="button" className="settings-close" onClick={props.onClose}>
            关闭
          </button>
        </header>
        <nav className="settings-tabs">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`settings-tab${tab === entry.id ? ' active' : ''}`}
              data-tab={entry.id}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </nav>
        <div className="settings-content">
          {tab === 'general' && (
            <section className="settings-panel" data-testid="general-settings">
              <h2>General</h2>
              <div className="settings-option-row">
                <div><strong>Approval mode</strong><p className="settings-hint">The mode applies to this task window. Full access always requires confirmation.</p></div>
                <select aria-label="Approval mode" value={props.permissionMode} onChange={(event) => props.onPermissionModeChange(event.target.value as PermissionMode)}>
                  <option value="confirm_all">更改前询问</option>
                  <option value="auto_edit">自动编辑</option>
                  <option value="full_auto">完全访问</option>
                </select>
              </div>
              <div className="settings-option-row">
                <div><strong>Theme</strong><p className="settings-hint">Choose the canvas and panel appearance.</p></div>
                <select aria-label="Theme" value={props.theme} onChange={(event) => props.onThemeChange(event.target.value as ThemePreference)}>
                  <option value="system">System</option>
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                </select>
              </div>
              <div className="settings-option-row">
                <div><strong>Language</strong><p className="settings-hint">UI language preference for the Desktop shell.</p></div>
                <select aria-label="Language" value={props.language} onChange={(event) => props.onLanguageChange(event.target.value as DesktopLanguage)}>
                  <option value="zh-CN">简体中文</option>
                  <option value="en-US">English</option>
                </select>
              </div>
            </section>
          )}
          {tab === 'model' && (
            <section className="settings-panel">
              <h2>模型</h2>
              {props.models.loading && !props.models.supported ? (
                <p className="settings-hint">加载中…</p>
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
                  {props.models.loading && <p className="settings-hint">加载中…</p>}
                  {props.models.error !== null && (
                    <p className="settings-error">{props.models.error}</p>
                  )}
                  {(props.models.snapshot?.models ?? []).length === 0 && (
                    <p className="settings-hint">尚无模型。请在此处选择 Provider、填写 API Key 并探测可用模型。</p>
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
                            {model.active && <span className="model-badge">当前</span>}
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
                                设为当前
                              </button>
                            )}
                            <button
                              type="button"
                              className="model-test"
                              onClick={() => void props.models.testConnection(model.id)}
                            >
                              测试连接
                            </button>
                            <button
                              type="button"
                              className="model-remove"
                              onClick={() => void props.models.remove(model.id)}
                            >
                               删除
                            </button>
                          </div>
                        </div>
                      ))}
                    </section>
                  ))}
                </div>
              )}
              {props.models.supported && <AddModelPanel models={props.models} onModelSelected={props.onModelSelected} />}
            </section>
          )}
          {tab === 'apikey' && (
            <section className="settings-panel">
              <h2>API Key</h2>
              {props.models.loading && !props.models.supported ? (
                <p className="settings-hint">加载中…</p>
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
                    <p className="settings-hint">尚无模型可配置密钥。</p>
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
          {tab === 'workspace' && (
            <section className="settings-panel">
              <h2>工作区</h2>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">当前生效</span>
                  <span className="workspace-path">{props.effectiveWorkspaceRoot}</span>
                </div>
                <div className="workspace-row">
                  <span className="label">已保存设置</span>
                  <span className="workspace-path">
                    {props.savedWorkspaceRoot ?? '未设置（使用后端仓库根目录）'}
                  </span>
                </div>
                <div className="workspace-actions">
                  <button
                    type="button"
                    className="workspace-pick"
                    disabled={props.picking}
                    onClick={() => void props.onPickWorkspace()}
                  >
                    {props.picking ? '选择中…' : '选择目录'}
                  </button>
                  <button
                    type="button"
                    className="workspace-clear"
                    disabled={props.savedWorkspaceRoot === null || props.picking}
                    onClick={props.onClearWorkspace}
                  >
                    恢复默认
                  </button>
                </div>
                <p className="settings-hint">
                  新会话通过既有协议字段 session/new.workspace_root
                  使用所选目录；未设置时回退到后端仓库根目录。协议与 schema.json 均未改动。
                </p>
              </div>
            </section>
          )}
          {tab === 'diagnostics' && (
            <section className="settings-panel">
              <h2>更新与诊断</h2>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">当前版本</span>
                  <span className="workspace-path">{props.appVersion}</span>
                </div>
                <div className="workspace-row">
                  <span className="label">更新状态</span>
                  <span className="workspace-path">
                    {updateStatus !== null ? UPDATE_STATUS_LABELS[updateStatus] : '加载中…'}
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
                    检查更新
                  </button>
                  {updateStatus === 'available' && (
                    <button
                      type="button"
                      className="workspace-pick"
                      onClick={() => void diagnostics.downloadUpdate()}
                    >
                      下载更新
                    </button>
                  )}
                  {updateStatus === 'downloaded' && (
                    <button
                      type="button"
                      className="workspace-pick"
                      onClick={() => diagnostics.installUpdate()}
                    >
                      立即重启安装
                    </button>
                  )}
                </div>
                <p className="settings-hint">
                  更新为手动触发：检查、下载、安装均由你点击执行，启动时不会强制检查；检查或下载失败不会影响当前版本运行。
                </p>
              </div>
              <div className="workspace-card">
                <div className="workspace-row">
                  <span className="label">崩溃上报</span>
                  <label className="settings-toggle">
                    <input
                      type="checkbox"
                      checked={diagnostics.consent === true}
                      disabled={diagnostics.consent === null}
                      onChange={(event) => void diagnostics.setConsent(event.target.checked)}
                    />
                    允许上传脱敏崩溃诊断（默认关闭，切换立即生效）
                  </label>
                </div>
                <p className="settings-hint">
                  诊断包只包含版本、平台、协议状态与日志摘要，不含 API Key、代码、完整 prompt
                  或工具输入输出。未开启同意时仅在本地记录。
                </p>
                <h3>最近诊断</h3>
                {diagnostics.reports.length === 0 ? (
                  <p className="settings-hint">暂无诊断记录。</p>
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
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
