// 添加/编辑模型连接（MOD-01～06、MOD-16、MOD-21）：
// 预设只填名字+URL；自定义显示名称与 Base URL；api_key 走密码输入，
// 只提交不回显，编辑时空值代表“保留现有 key”。组件每次打开由父层
// 重新挂载，关闭即丢弃未保存的密钥草稿。
import { useState, type FormEvent } from "react"

import { Button } from "../../components/ui/button"
import { Modal } from "../../components/ui/dialog"
import { IconEye, IconEyeOff } from "../../components/icons"
import {
  ApiError,
  createClient,
  type ModelConnection,
  type ProviderPreset,
} from "../../sdk/client"
import { apiErrorText, errorWithCode } from "../../sdk/errors"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

const CUSTOM = "__custom"

export function ConnectionFormDialog({
  connection,
  presets,
  onClose,
  onSaved,
}: {
  // null = 新建；否则为编辑该连接。
  connection: ModelConnection | null
  presets: ProviderPreset[]
  onClose: () => void
  onSaved: () => void
}) {
  const editing = connection !== null
  const [presetId, setPresetId] = useState("")
  const [providerName, setProviderName] = useState(connection?.provider_name ?? "")
  const [baseUrl, setBaseUrl] = useState(connection?.base_url ?? "")
  const [displayName, setDisplayName] = useState(connection?.display_name ?? "")
  const [apiKey, setApiKey] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [fieldError, setFieldError] = useState<{
    baseUrl?: string
    apiKey?: string
    preset?: string
  }>({})

  const custom = presetId === CUSTOM

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    setFieldError({})
    try {
      if (editing && connection) {
        // 编辑：只提交变化字段；api_key 留空 = 保留现有（MOD-04/21）。
        const body: { display_name?: string; base_url?: string; api_key?: string } = {}
        const name = displayName.trim()
        if (name && name !== connection.display_name) body.display_name = name
        const url = baseUrl.trim()
        if (url && url !== connection.base_url) body.base_url = url
        if (apiKey.trim()) body.api_key = apiKey.trim()
        await api.patchModelConnection(connection.id, body)
      } else {
        const key = apiKey.trim()
        if (!presetId) {
          setFieldError({ preset: "请选择服务商预设或“自定义”" })
          return
        }
        if (!key) {
          setFieldError({ apiKey: "请输入 API Key" })
          return
        }
        if (custom && !baseUrl.trim()) {
          setFieldError({ baseUrl: "请输入接口地址（HTTPS）" })
          return
        }
        const body = custom
          ? {
              base_url: baseUrl.trim(),
              ...(providerName.trim() ? { provider_name: providerName.trim() } : {}),
              api_key: key,
              ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
            }
          : {
              preset_id: presetId,
              api_key: key,
              ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
            }
        await api.createModelConnection(body)
      }
      onSaved()
      onClose()
    } catch (err) {
      // 失败保留非秘密字段与已输入内容，不关表单（MOD-06）。
      if (err instanceof ApiError && err.code === "INVALID_BASE_URL") {
        setFieldError({ baseUrl: apiErrorText(err) })
      } else if (err instanceof ApiError && err.code === "INVALID_INPUT") {
        setError(errorWithCode(err))
      } else {
        setError(errorWithCode(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} label={editing ? "编辑连接" : "添加连接"}>
      <form onSubmit={submit} className="space-y-4 p-5">
        <h3 className="text-base font-semibold">
          {editing ? "编辑连接" : "添加连接"}
        </h3>
        {editing && connection ? (
          <p className="text-xs text-muted">
            {connection.provider_name} · {connection.base_url}
          </p>
        ) : (
          <>
            <label className="block text-sm font-medium">
              服务商
              <select
                className={inputClass}
                value={presetId}
                onChange={(event) => setPresetId(event.target.value)}
                required
              >
                <option value="" disabled>
                  选择预设…
                </option>
                {presets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}（{item.base_url}）
                  </option>
                ))}
                <option value={CUSTOM}>自定义服务商</option>
              </select>
              {fieldError.preset ? (
                <span className="mt-1 block text-xs text-failure">
                  {fieldError.preset}
                </span>
              ) : null}
            </label>
            {custom ? (
              <>
                <label className="block text-sm font-medium">
                  Base URL
                  <input
                    className={inputClass}
                    type="url"
                    name="base-url"
                    placeholder="https://api.example.com/v1"
                    autoComplete="off"
                    required
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                  />
                  {fieldError.baseUrl ? (
                    <span className="mt-1 block text-xs text-failure">
                      {fieldError.baseUrl}
                    </span>
                  ) : null}
                </label>
                <label className="block text-sm font-medium">
                  服务商名称（可选）
                  <input
                    className={inputClass}
                    type="text"
                    name="provider-name"
                    placeholder="留空则按地址自动识别"
                    autoComplete="off"
                    value={providerName}
                    onChange={(event) => setProviderName(event.target.value)}
                  />
                </label>
              </>
            ) : null}
          </>
        )}
        {editing ? (
          <label className="block text-sm font-medium">
            Base URL
            <input
              className={inputClass}
              type="url"
              name="base-url"
              autoComplete="off"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
            {fieldError.baseUrl ? (
              <span className="mt-1 block text-xs text-failure">
                {fieldError.baseUrl}
              </span>
            ) : null}
          </label>
        ) : null}
        <label className="block text-sm font-medium">
          显示名称（可选）
          <input
            className={inputClass}
            type="text"
            name="display-name"
            autoComplete="off"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className="block text-sm font-medium">
          API Key{editing ? "（留空保留现有 Key）" : ""}
          <span className="relative mt-1 block">
            <input
              className={inputClass + " mt-0 pr-10"}
              // 密码输入：服务端永不回传明文，眼睛只切当前草稿可见性。
              type={showKey ? "text" : "password"}
              name="api-key"
              autoComplete="new-password"
              required={!editing}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
            <button
              type="button"
              aria-label={showKey ? "隐藏 API Key" : "显示 API Key"}
              title={showKey ? "隐藏 API Key" : "显示 API Key"}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:bg-sidebar"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? <IconEyeOff size={15} /> : <IconEye size={15} />}
            </button>
          </span>
          {fieldError.apiKey ? (
            <span className="mt-1 block text-xs text-failure">
              {fieldError.apiKey}
            </span>
          ) : null}
        </label>
        {error ? (
          <p role="alert" className="text-sm text-failure">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="submit" size="sm" disabled={busy}>
            {busy ? "保存中…" : editing ? "保存修改" : "保存连接"}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
