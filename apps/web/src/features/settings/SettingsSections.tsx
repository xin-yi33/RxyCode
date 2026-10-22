import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { NavLink, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { persistLocaleCookie, type LocaleSetting } from "../../lib/i18n"
import {
  createClient,
  type DeviceStatus,
  type Me,
  type NotificationItem,
  type SessionListItem,
} from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { ACCENTS, THEMES } from "../../lib/appearance"
import { useApplyAppearance, usePatchPreferences, usePreferences } from "../../state/prefs"
import { useUi } from "../../state/ui"
import { useAuth, useLogout } from "../auth/useAuth"
import { runStatusKind, runStatusText } from "../runs/status"
import { AboutDialog } from "./AboutDialog"

const api = createClient()

const DEVICE_STATUS_TEXT: Record<string, string> = {
  active: "当前设备持有使用权",
  held_elsewhere: "另一台设备使用中",
  none: "—",
}

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  )
}

// ---- 通用：语言 + 账号 + 设备 ----------------------------------------------

export function GeneralSection() {
  const me = useQuery<Me>({ queryKey: ["me"], enabled: false })
  const auth = useAuth()
  const queryClient = useQueryClient()
  const { logout, busy: logoutBusy, error: logoutError } = useLogout()
  const prefs = usePreferences()
  const patch = usePatchPreferences()
  const [claimBusy, setClaimBusy] = useState(false)
  const [claimError, setClaimError] = useState("")
  const [aboutOpen, setAboutOpen] = useState(false)
  const [prefError, setPrefError] = useState("")

  const device = useQuery<DeviceStatus>({
    queryKey: ["deviceStatus"],
    queryFn: ({ signal }) => api.getDeviceStatus(signal),
    enabled: auth.status === "authed",
    staleTime: 30_000,
  })

  const setLocale = (value: LocaleSetting) => {
    persistLocaleCookie(value)
    patch.mutate(
      { locale: value, expected_revision: prefs.data?.revision },
      { onError: (err) => setPrefError(apiErrorText(err)) },
    )
  }

  return (
    <div className="space-y-4">
      <Section title="语言">
        <div className="flex items-center gap-3 text-sm">
          <select
            value={prefs.data?.locale ?? "auto"}
            onChange={(e) => setLocale(e.target.value as LocaleSetting)}
            className="rounded-md border border-border bg-background px-2 py-1.5"
            aria-label="界面语言"
          >
            <option value="auto">跟随系统</option>
            <option value="zh-CN">简体中文</option>
            <option value="en">English</option>
          </select>
          {patch.isPending ? <span className="text-xs text-muted">保存中…</span> : null}
        </div>
        {prefError ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {prefError}
          </p>
        ) : null}
      </Section>

      <Section title="账号">
        <dl className="space-y-1 text-sm text-muted">
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">邮箱</dt>
            <dd className="truncate">{me.data?.user?.email ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">组织</dt>
            <dd className="truncate">{me.data?.organization.tenant_id ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">角色</dt>
            <dd>{me.data?.membership.role ?? "—"}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="w-20 shrink-0">设备</dt>
            <dd className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                {device.isPending
                  ? "…"
                  : device.isError
                    ? "无法获取设备状态"
                    : (DEVICE_STATUS_TEXT[device.data?.status ?? ""] ?? device.data?.status ?? "—")}
              </span>
              {device.data?.status === "held_elsewhere" ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={claimBusy}
                  onClick={() => {
                    setClaimBusy(true)
                    setClaimError("")
                    api
                      .claimDevice()
                      .then(() => void queryClient.invalidateQueries())
                      .catch((err: unknown) => setClaimError(apiErrorText(err)))
                      .finally(() => setClaimBusy(false))
                  }}
                >
                  {claimBusy ? "切换中…" : "切换到此设备"}
                </Button>
              ) : null}
            </dd>
          </div>
          {claimError ? (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0" />
              <dd role="alert" className="text-xs text-failure">
                {claimError}
              </dd>
            </div>
          ) : null}
        </dl>
        <div className="mt-4 flex gap-2">
          <Button variant="outline" size="sm" disabled={logoutBusy} onClick={() => void logout()}>
            {logoutBusy ? "退出中…" : "登出"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAboutOpen(true)}>
            关于
          </Button>
        </div>
        {logoutError ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {logoutError}
          </p>
        ) : null}
      </Section>
      {aboutOpen ? <AboutDialog onClose={() => setAboutOpen(false)} /> : null}
    </div>
  )
}

// ---- 外观 ------------------------------------------------------------------

// ---- 外观（APP-01..16） -----------------------------------------------------

const HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/

/** APP-10/11 数字输入 + 上下 stepper（失焦/回车校验，范围钳制）。 */
function FontStepper({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}) {
  const [text, setText] = useState(String(value))
  const [err, setErr] = useState(false)
  const commit = (raw: string) => {
    const n = Number.parseInt(raw, 10)
    if (Number.isNaN(n) || n < min || n > max) {
      setErr(true)
      setText(String(value))
      return
    }
    setErr(false)
    setText(String(n))
    if (n !== value) onChange(n)
  }
  return (
    <label className="flex items-center justify-between gap-4 text-sm">
      {label}
      <span className="flex items-center gap-1">
        <button
          type="button"
          aria-label={`${label} -1`}
          className="h-6 w-6 rounded border border-border text-xs disabled:opacity-40"
          disabled={value <= min}
          onClick={() => onChange(value - 1)}
        >
          −
        </button>
        <span className="flex items-baseline gap-1">
          <input
            value={text}
            inputMode="numeric"
            aria-label={label}
            aria-invalid={err}
            onChange={(e) => setText(e.target.value)}
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit(e.currentTarget.value)
            }}
            className="w-12 rounded border border-border bg-background px-1 py-0.5 text-center text-sm"
          />
          <span className="text-xs text-muted">px</span>
        </span>
        <button
          type="button"
          aria-label={`${label} +1`}
          className="h-6 w-6 rounded border border-border text-xs disabled:opacity-40"
          disabled={value >= max}
          onClick={() => onChange(value + 1)}
        >
          +
        </button>
      </span>
    </label>
  )
}

/** APP-07/08 色盘 + hex 输入同一行，双向同步，非法值就地报错保留最后有效值。 */
function ColorField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (v: string) => void
}) {
  const [text, setText] = useState(value || "")
  const [invalid, setInvalid] = useState(false)
  const commit = (raw: string) => {
    if (raw === "" || HEX_RE.test(raw.trim())) {
      setInvalid(false)
      const v = raw.trim()
      setText(v)
      onChange(v)
    } else {
      setInvalid(true)
      setText(value || "")
    }
  }
  const picker = value && HEX_RE.test(value) ? value : "#ffffff"
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span>{label}</span>
      <span className="flex items-center gap-2">
        <input
          type="color"
          value={picker.length === 7 ? picker : "#ffffff"}
          aria-label={`${label}色盘`}
          onChange={(e) => {
            setText(e.target.value)
            setInvalid(false)
            onChange(e.target.value)
          }}
          className="h-7 w-9 cursor-pointer rounded border border-border bg-transparent p-0"
        />
        <input
          value={text}
          aria-label={label}
          aria-invalid={invalid}
          placeholder="#FCFCFC"
          onChange={(e) => setText(e.target.value)}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(e.currentTarget.value)
          }}
          className="w-24 rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </span>
    </div>
  )
}

export function AppearanceSection() {
  const prefs = usePreferences()
  const patch = usePatchPreferences()
  const showToast = useUi((state) => state.showToast)
  const [error, setError] = useState("")
  const [advanced, setAdvanced] = useState(false)
  const [modeTab, setModeTab] = useState<"light" | "dark">("light")
  const appearance = prefs.data?.appearance

  useApplyAppearance(prefs.data)

  const save = (body: Parameters<typeof patch.mutate>[0]) => {
    setError("")
    patch.mutate(
      { ...body, expected_revision: prefs.data?.revision },
      { onError: (err) => setError(apiErrorText(err)) },
    )
  }
  const setAppearance = (part: Partial<NonNullable<typeof appearance>>) =>
    save({ appearance: part })

  if (prefs.isPending) return <p className="text-sm text-muted">正在加载偏好…</p>
  if (prefs.isError)
    return (
      <p role="alert" className="text-sm text-failure">
        {apiErrorText(prefs.error)}
      </p>
    )

  const separate = appearance?.separate_modes ?? false
  const shared = appearance?.shared ?? {}
  // APP-13：两套模式时编辑当前 Tab 的那一套；否则编辑 shared。
  const scopedProfile =
    separate
      ? (modeTab === "light" ? appearance?.light : appearance?.dark) ?? {}
      : shared
  const setProfile = (patchPart: Record<string, unknown>) => {
    if (separate) {
      const key = modeTab === "light" ? "light" : "dark"
      const base = (appearance?.[key] ?? {}) as Record<string, unknown>
      save({ appearance: { [key]: { ...base, ...patchPart } } })
    } else {
      save({ appearance: { shared: { ...shared, ...patchPart } } })
    }
  }

  const num = (v: unknown, d: number) => (typeof v === "number" ? v : d)
  const contrastValue = num(scopedProfile.contrast, scopedProfile.contrast === "high" ? 80 : 45)
  const currentThemeId = String(scopedProfile.theme_id ?? "")

  // APP-02：只列本地随包主题；切换即把主题 token 写进 profile（预览立即生效）。
  const pickTheme = (themeId: string) => {
    const spec = THEMES.find((t0) => t0.id === themeId)
    if (!spec) return
    setProfile({
      theme_id: spec.id,
      accent: spec.accent,
      background: spec.background,
      foreground: spec.foreground,
    })
  }

  // APP-04/05：导出/复制的是已归一化的外观 JSON —— 无 Key/会话/账号字段。
  const exportJson = () =>
    JSON.stringify(
      {
        kind: "rxycode-appearance",
        version: 1,
        appearance: prefs.data?.appearance ?? {},
      },
      null,
      2,
    )
  const downloadTheme = () => {
    const blob = new Blob([exportJson()], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "rxycode-theme.json"
    a.click()
    URL.revokeObjectURL(url)
  }
  const copyTheme = async () => {
    try {
      await navigator.clipboard.writeText(exportJson())
      showToast("主题 JSON 已复制")
    } catch {
      showToast("复制失败，请使用下载导出")
    }
  }

  const DEFAULTS = {
    mode: "system",
    separate_modes: false,
    shared: {},
    light: null,
    dark: null,
    reduced_motion: "system",
    diff_markers: "color",
  } as const

  return (
    <div className="space-y-4">
      <Section title="主题模式">
        {/* APP-01 三模式缩略图 */}
        <div className="flex gap-3" role="radiogroup" aria-label="主题模式">
          {(
            [
              ["system", "跟随系统"],
              ["light", "浅色"],
              ["dark", "深色"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={appearance?.mode === id}
              title={label}
              onClick={() => setAppearance({ mode: id })}
              className="flex flex-col items-center gap-1"
            >
              <span
                aria-hidden
                className={
                  "flex h-12 w-16 items-center justify-center rounded-md border text-sm " +
                  (appearance?.mode === id
                    ? "border-accent ring-2 ring-accent/30"
                    : "border-border")
                }
                style={{
                  background:
                    id === "dark"
                      ? "#111114"
                      : id === "light"
                        ? "#ffffff"
                        : "linear-gradient(90deg,#ffffff 50%,#111114 50%)",
                  color: id === "dark" ? "#e7e7ea" : "#1c1c1e",
                }}
              >
                Aa
              </span>
              <span className="text-xs text-muted">{label}</span>
            </button>
          ))}
        </div>
      </Section>

      <Section title="主题">
        <div className="flex items-center gap-2 text-sm">
          {/* APP-02/03 主题下拉：Aa 色块 + 名称 */}
          <label htmlFor="theme-select" className="text-muted">
            主题
          </label>
          <select
            id="theme-select"
            value={currentThemeId}
            onChange={(e) => pickTheme(e.target.value)}
            className="w-56 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">自定义（未选主题）</option>
            {THEMES.map((theme) => (
              <option key={theme.id} value={theme.id}>
                {theme.name}
              </option>
            ))}
          </select>
          {/* APP-04/05 下载 / 复制 */}
          <button
            type="button"
            aria-label="下载主题 JSON"
            title="下载主题 JSON"
            className="rounded-md border border-border p-1.5 text-muted hover:bg-sidebar"
            onClick={downloadTheme}
          >
            ⭳
          </button>
          <button
            type="button"
            aria-label="复制主题 JSON"
            title="复制主题 JSON"
            className="rounded-md border border-border p-1.5 text-muted hover:bg-sidebar"
            onClick={() => void copyTheme()}
          >
            ⧉
          </button>
        </div>
        {/* APP-03：各主题 Aa 缩略预览（用主题实际 token）。 */}
        <div className="mt-2 flex flex-wrap gap-2">
          {THEMES.map((theme) => (
            <button
              key={theme.id}
              type="button"
              title={theme.name}
              aria-pressed={currentThemeId === theme.id}
              onClick={() => pickTheme(theme.id)}
              className={
                "flex h-9 w-12 items-center justify-center rounded-md border text-sm " +
                (currentThemeId === theme.id
                  ? "border-accent ring-2 ring-accent/30"
                  : "border-border")
              }
              style={{ background: theme.background, color: theme.foreground }}
            >
              Aa
            </button>
          ))}
        </div>
      </Section>

      <Section title="颜色">
        <div className="space-y-3">
          {/* APP-06 强调色 */}
          <div className="flex items-center justify-between gap-4 text-sm">
            <span>强调色</span>
            <select
              value={
                ACCENTS.find((a) => a.color === (scopedProfile.accent ?? ""))?.id ??
                "default"
              }
              onChange={(e) => {
                const spec = ACCENTS.find((a) => a.id === e.target.value)
                setProfile({ accent: spec?.color ?? "" })
              }}
              className="w-48 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              aria-label="强调色"
            >
              {ACCENTS.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          {/* APP-07/08 背景/前景色 */}
          <ColorField
            label="背景色"
            value={String(scopedProfile.background ?? "")}
            onChange={(v) => setProfile({ background: v })}
          />
          <ColorField
            label="前景色"
            value={String(scopedProfile.foreground ?? "")}
            onChange={(v) => setProfile({ foreground: v })}
          />
        </div>
      </Section>

      {/* APP-13 分别设置浅色和深色 */}
      <Section title="分模式设置">
        <div className="flex items-center justify-between text-sm">
          <span>分别设置浅色和深色</span>
          <button
            type="button"
            role="switch"
            aria-checked={separate}
            className={
              "relative h-5 w-9 rounded-full transition " +
              (separate ? "bg-accent" : "bg-border")
            }
            onClick={() => setAppearance({ separate_modes: !separate })}
          >
            <span
              aria-hidden
              className={
                "absolute top-0.5 h-4 w-4 rounded-full bg-white transition " +
                (separate ? "left-4.5 translate-x-0" : "left-0.5")
              }
              style={{ left: separate ? "1.125rem" : "0.125rem" }}
            />
          </button>
        </div>
        {separate ? (
          <div className="mt-2 flex gap-1" role="tablist" aria-label="编辑模式">
            {(
              [
                ["light", "编辑浅色"],
                ["dark", "编辑深色"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={modeTab === id}
                onClick={() => setModeTab(id)}
                className={
                  "rounded-full px-3 py-1 text-xs " +
                  (modeTab === id
                    ? "bg-foreground text-background"
                    : "border border-border text-muted")
                }
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
      </Section>

      {/* APP-09 高级折叠 */}
      <Section title="">
        <button
          type="button"
          aria-expanded={advanced}
          className="flex items-center gap-1 text-sm font-medium"
          onClick={() => setAdvanced((v) => !v)}
        >
          <span aria-hidden className="inline-block w-3 text-[10px]">
            {advanced ? "▾" : "▸"}
          </span>
          高级
        </button>
        {advanced ? (
          <div className="mt-3 space-y-3">
            <FontStepper
              label="界面字号"
              value={num(scopedProfile.ui_font_px, 14)}
              min={12}
              max={22}
              onChange={(v) => setProfile({ ui_font_px: v })}
            />
            <FontStepper
              label="代码字号"
              value={num(scopedProfile.code_font_px, 12)}
              min={11}
              max={24}
              onChange={(v) => setProfile({ code_font_px: v })}
            />
            {/* APP-14 对比度滑块 0–100 */}
            <label className="flex items-center justify-between gap-4 text-sm">
              对比度
              <span className="flex items-center gap-2">
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={contrastValue}
                  aria-label="对比度"
                  onChange={(e) =>
                    setProfile({ contrast: Number(e.target.value) })
                  }
                />
                <span className="w-8 text-right text-muted">{contrastValue}</span>
              </span>
            </label>
            {/* APP-12 减少动态效果：系统/开/关 分段按钮 */}
            <div className="flex items-center justify-between text-sm">
              <span>减少动态效果</span>
              <span className="flex gap-1" role="radiogroup" aria-label="减少动态效果">
                {(
                  [
                    ["system", "系统"],
                    ["on", "开启"],
                    ["off", "关闭"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={(appearance?.reduced_motion ?? "system") === id}
                    onClick={() =>
                      setAppearance({
                        reduced_motion: id,
                      })
                    }
                    className={
                      "rounded-full px-2.5 py-0.5 text-xs " +
                      ((appearance?.reduced_motion ?? "system") === id
                        ? "bg-foreground text-background"
                        : "border border-border text-muted")
                    }
                  >
                    {label}
                  </button>
                ))}
              </span>
            </div>
            {/* APP-15 差异标记 */}
            <div className="flex items-center justify-between text-sm">
              <span>差异标记</span>
              <span className="flex gap-1" role="radiogroup" aria-label="差异标记">
                {(
                  [
                    ["color", "颜色"],
                    ["symbols", "+/− 符号"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={(appearance?.diff_markers ?? "color") === id}
                    onClick={() => setAppearance({ diff_markers: id })}
                    className={
                      "rounded-full px-2.5 py-0.5 text-xs " +
                      ((appearance?.diff_markers ?? "color") === id
                        ? "bg-foreground text-background"
                        : "border border-border text-muted")
                    }
                  >
                    {label}
                  </button>
                ))}
              </span>
            </div>
          </div>
        ) : null}
      </Section>

      {/* APP-16 恢复默认：只还原外观，不动 Key/聊天。 */}
      <button
        type="button"
        className="text-sm text-muted underline disabled:opacity-60"
        disabled={patch.isPending}
        onClick={() => setAppearance({ ...DEFAULTS })}
      >
        恢复默认外观
      </button>
      {error ? (
        <p role="alert" className="text-sm text-failure">
          {error}
        </p>
      ) : null}
      {patch.isPending ? <p className="text-xs text-muted">保存中…</p> : null}
    </div>
  )
}

// ---- 通知 ------------------------------------------------------------------

export function NotificationsSection() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const prefs = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: ({ signal }) => api.getNotificationPreferences(signal),
    enabled: auth.status === "authed",
  })
  const items = useQuery({
    queryKey: ["notifications"],
    queryFn: ({ signal }) => api.listNotifications({ limit: 30 }, signal),
    enabled: auth.status === "authed",
  })
  const [error, setError] = useState("")

  const saveChannels = useMutation({
    mutationFn: (body: { category_id: string; selected_channels: string[] }) =>
      api.patchNotificationPreferences({
        ...body,
        expected_revision: prefs.data?.revision,
      }),
    onSuccess: (data) =>
      queryClient.setQueryData(["notification-preferences"], data),
    onError: (err) => setError(apiErrorText(err)),
  })
  const markRead = useMutation({
    mutationFn: (id: string) => api.markNotificationRead(id, true),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  })

  const CATEGORY_LABEL: Record<string, string> = {
    agent_tasks: "Agent 任务",
    replies: "回复",
    scheduled_tasks: "定时任务",
    usage: "使用情况",
    health: "健康",
    group_chats: "群聊",
    library: "资料库",
    projects: "项目",
    personalized: "个性化提示",
    marketing: "营销",
  }
  const CATEGORY_REASON: Record<string, string> = {
    no_event_source: "该来源暂未接入，暂不可开启",
    no_smtp: "邮件投递未配置",
  }
  // 图32 胶囊下拉的固定选项 → 渠道数组；可用性由 allowed_channels 能力裁剪。
  const PRESETS: { value: string; label: string; channels: string[] }[] = [
    { value: "off", label: "关闭", channels: [] },
    { value: "in_app", label: "站内", channels: ["in_app"] },
    { value: "push", label: "推送", channels: ["push"] },
    { value: "email", label: "电子邮件", channels: ["email"] },
    { value: "push+email", label: "推送和电子邮件", channels: ["push", "email"] },
  ]
  const presetOf = (sel: string[]) => {
    const key = [...sel].sort().join("+")
    return (
      PRESETS.find((p) => [...p.channels].sort().join("+") === key)?.value ??
      "custom"
    )
  }
  const [busyRow, setBusyRow] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})

  // 推送是浏览器权限 + 真实订阅，不是 toast；拒绝/不支持就地说明。
  const ensurePush = async (): Promise<string | null> => {
    if (typeof Notification === "undefined" || !("PushManager" in window)) {
      return "当前浏览器不支持推送"
    }
    const perm = await Notification.requestPermission()
    if (perm !== "granted") return "浏览器拒绝了推送权限"
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (!sub) {
        // 没有服务端 VAPID 公钥时无法创建订阅——如实提示。
        const key = (import.meta.env.VITE_PUSH_VAPID_KEY as string | undefined) ?? ""
        if (!key) return "推送服务未配置（缺少 VAPID 公钥）"
        const created = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        })
        const json = created.toJSON() as {
          endpoint?: string
          keys?: { p256dh?: string; auth?: string }
        }
        if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
          return "推送订阅缺少密钥"
        }
        await api.addPushSubscription({
          endpoint: json.endpoint,
          keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
        })
      }
      return null
    } catch {
      return "无法建立推送订阅"
    }
  }

  type NotifyCategory = {
    id: string
    allowed_channels: string[]
    selected_channels: string[]
  }
  const applyPreset = async (cat: NotifyCategory, value: string) => {
    const preset = PRESETS.find((p) => p.value === value)
    if (!preset) return
    setBusyRow(cat.id)
    setRowErrors((prev) => ({ ...prev, [cat.id]: "" }))
    try {
      if (preset.channels.includes("push")) {
        const deny = await ensurePush()
        if (deny) {
          setRowErrors((prev) => ({ ...prev, [cat.id]: deny }))
          return
        }
      }
      await saveChannels.mutateAsync({
        category_id: cat.id,
        selected_channels: preset.channels,
      })
    } catch (err) {
      setRowErrors((prev) => ({ ...prev, [cat.id]: apiErrorText(err) }))
    } finally {
      setBusyRow(null)
    }
  }

  return (
    <div className="space-y-4">
      <Section title="通知类别">
        {prefs.isPending ? (
          <p className="text-sm text-muted">正在加载…</p>
        ) : prefs.isError ? (
          <p role="alert" className="text-sm text-failure">
            {apiErrorText(prefs.error)}
          </p>
        ) : (
          <ul className="space-y-2">
            {prefs.data.categories.map((cat) => {
              const preset = presetOf(cat.selected_channels)
              const busy = busyRow === cat.id
              const err = rowErrors[cat.id]
              return (
                <li
                  key={cat.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {CATEGORY_LABEL[cat.id] ?? cat.label}
                      {cat.id === "scheduled_tasks" ? (
                        <NavLink
                          to="/scheduled"
                          className="text-xs font-normal text-muted underline"
                        >
                          管理任务
                        </NavLink>
                      ) : null}
                    </div>
                    <p className="text-xs text-muted">
                      {!cat.available
                        ? (CATEGORY_REASON[cat.reason] ?? cat.reason ?? "暂不可用")
                        : err || cat.description || ""}
                    </p>
                  </div>
                  <select
                    aria-label={CATEGORY_LABEL[cat.id] ?? cat.label}
                    value={preset}
                    disabled={!cat.available || busy}
                    onChange={(e) => void applyPreset(cat, e.target.value)}
                    className="shrink-0 rounded-full border border-border bg-background px-3 py-1 text-xs disabled:opacity-50"
                  >
                    {PRESETS.map((p) => (
                      <option
                        key={p.value}
                        value={p.value}
                        disabled={p.channels.some((c) => !cat.allowed_channels.includes(c))}
                      >
                        {p.label}
                      </option>
                    ))}
                    {preset === "custom" ? (
                      <option value="custom" disabled>
                        自定义组合
                      </option>
                    ) : null}
                  </select>
                </li>
              )
            })}
          </ul>
        )}
      </Section>
      <Section title="最近通知">
        {items.isPending ? (
          <p className="text-sm text-muted">正在加载…</p>
        ) : items.isError ? (
          <p role="alert" className="text-sm text-failure">
            {apiErrorText(items.error)}
          </p>
        ) : (items.data?.notifications ?? []).length === 0 ? (
          <p className="text-sm text-muted">暂无通知</p>
        ) : (
          <ul className="space-y-1">
            {items.data.notifications.map((n: NotificationItem) => (
              <li
                key={n.id}
                className={
                  "flex items-start justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm " +
                  (n.read ? "opacity-60" : "")
                }
              >
                <div className="min-w-0">
                  <p className="truncate">{n.title || n.body}</p>
                  <p className="text-xs text-muted">
                    {n.created_at ? new Date(n.created_at).toLocaleString() : ""}
                  </p>
                </div>
                {!n.read ? (
                  <button
                    type="button"
                    className="shrink-0 text-xs text-muted underline"
                    onClick={() => markRead.mutate(n.id)}
                  >
                    标为已读
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>
      {error ? (
        <p role="alert" className="text-sm text-failure">
          {error}
        </p>
      ) : null}
    </div>
  )
}

// ---- 已归档会话 --------------------------------------------------------------

export function ArchivedSection() {
  const queryClient = useQueryClient()
  const [error, setError] = useState("")
  const [pendingDelete, setPendingDelete] = useState<SessionListItem | null>(null)
  // FR-ARCHIVE-01：搜索 + 来源/项目/排序筛选写进 URL query。
  const [params, setParams] = useSearchParams()
  const q = params.get("q") ?? ""
  const origin = params.get("origin") ?? "all"
  const projectId = params.get("project") ?? ""
  const sort = params.get("sort") === "created_at" ? "created_at" : "updated_at"
  const patchParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
  })
  const archived = useQuery({
    queryKey: ["sessions", "archived", q, origin, projectId, sort],
    queryFn: ({ signal }) =>
      api.listSessions(
        {
          archived: "true",
          limit: 50,
          sort,
          q: q.trim() || undefined,
          origin: origin === "all" ? undefined : (origin as "local" | "cloud"),
          project_id: projectId || undefined,
        },
        signal,
      ),
  })
  const unarchive = useMutation({
    mutationFn: (s: SessionListItem) =>
      api.unarchiveSession(s.id, { expected_revision: s.revision }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
    onError: (err) => setError(apiErrorText(err)),
  })
  const remove = useMutation({
    mutationFn: (s: SessionListItem) =>
      api.deleteSession(s.id, { expected_revision: s.revision, confirm: true }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
      setPendingDelete(null)
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  const items = archived.data?.sessions ?? []
  // 分组卡片：按项目名分组展示。
  const groups = new Map<string, SessionListItem[]>()
  for (const s of items) {
    const key = s.project_name || "未归属项目"
    const list = groups.get(key) ?? []
    list.push(s)
    groups.set(key, list)
  }

  const input =
    "rounded-md border border-border bg-background px-2 py-1.5 text-sm"

  return (
    <Section title="已归档会话">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => patchParam("q", e.target.value)}
          placeholder="搜索归档标题…"
          aria-label="搜索归档会话"
          className={input + " min-w-40 flex-1"}
        />
        <select
          value={origin}
          onChange={(e) => patchParam("origin", e.target.value)}
          className={input}
          aria-label="来源"
        >
          <option value="all">全部来源</option>
          <option value="local">本机</option>
          <option value="cloud">云端</option>
        </select>
        <select
          value={projectId}
          onChange={(e) => patchParam("project", e.target.value)}
          className={input}
          aria-label="项目"
        >
          <option value="">全部项目</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => patchParam("sort", e.target.value)}
          className={input}
          aria-label="排序"
        >
          <option value="updated_at">最近更新</option>
          <option value="created_at">创建时间</option>
        </select>
      </div>
      {archived.isPending ? (
        <p className="text-sm text-muted">正在加载…</p>
      ) : archived.isError ? (
        <p role="alert" className="text-sm text-failure">
          {apiErrorText(archived.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted">没有已归档的会话</p>
      ) : (
        <div className="space-y-3">
          {[...groups.entries()].map(([group, list]) => (
            <div key={group} className="rounded-lg border border-border p-2">
              <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-muted">
                {group}
              </p>
              <ul className="space-y-1">
                {list.map((s) => {
                  const status = s.last_run?.status ?? ""
                  return (
                    <li
                      key={s.id}
                      className="flex items-center justify-between gap-3 rounded-md px-2 py-2 text-sm hover:bg-sidebar"
                    >
                      <NavLink to={`/app/s/${s.id}`} className="min-w-0 flex-1 truncate hover:underline">
                        {s.title || "未命名会话"}
                        {s.archived_at ? (
                          <span className="ml-2 text-xs text-muted">
                            归档于 {new Date(s.archived_at).toLocaleDateString()}
                          </span>
                        ) : null}
                      </NavLink>
                      {status ? (
                        <span className={"shrink-0 rounded-full px-2 py-0.5 text-xs " + chipClass[runStatusKind(status)]}>
                          {runStatusText(status)}
                        </span>
                      ) : null}
                      <button
                        type="button"
                        className="shrink-0 text-xs text-muted underline"
                        disabled={unarchive.isPending}
                        onClick={() => unarchive.mutate(s)}
                      >
                        取消归档
                      </button>
                      <button
                        type="button"
                        className="shrink-0 text-xs text-failure underline"
                        disabled={remove.isPending}
                        onClick={() => setPendingDelete(s)}
                      >
                        删除
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-failure">
          {error}
        </p>
      ) : null}
      {pendingDelete ? (
        <div
          role="presentation"
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
        >
          <div
            role="alertdialog"
            aria-modal="true"
            className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
          >
            <h2 className="text-base font-semibold">删除聊天</h2>
            <p className="mt-1 truncate text-sm font-medium">
              {pendingDelete.title || "未命名会话"}
            </p>
            <p className="mt-2 text-sm text-muted">永久删除，无法撤销</p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                autoFocus
                className="rounded-md border border-border px-3 py-1.5 text-sm"
                onClick={() => setPendingDelete(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="rounded-md bg-failure px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
                disabled={remove.isPending}
                onClick={() => remove.mutate(pendingDelete)}
              >
                删除会话
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </Section>
  )
}
