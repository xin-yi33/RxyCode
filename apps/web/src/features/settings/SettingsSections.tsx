import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { NavLink } from "react-router"

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
import { useApplyAppearance, usePatchPreferences, usePreferences } from "../../state/prefs"
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

export function AppearanceSection() {
  const prefs = usePreferences()
  const patch = usePatchPreferences()
  const [error, setError] = useState("")
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

  const shared = appearance?.shared ?? {}

  return (
    <div className="space-y-4">
      <Section title="主题模式">
        <div className="flex gap-1" role="radiogroup" aria-label="主题模式">
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
              onClick={() => setAppearance({ mode: id })}
              className={
                "rounded-full px-3 py-1 text-sm " +
                (appearance?.mode === id
                  ? "bg-foreground text-background"
                  : "border border-border text-muted")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </Section>
      <Section title="字体与排版">
        <div className="space-y-3 text-sm">
          <label className="flex items-center justify-between gap-4">
            界面字号
            <span className="flex items-center gap-2">
              <input
                type="range"
                min={12}
                max={18}
                step={1}
                value={shared.ui_font_px ?? 14}
                onChange={(e) =>
                  setAppearance({
                    shared: { ...shared, ui_font_px: Number(e.target.value) },
                  })
                }
              />
              <span className="w-8 text-right text-muted">{shared.ui_font_px ?? 14}px</span>
            </span>
          </label>
          <label className="flex items-center justify-between gap-4">
            代码字号
            <span className="flex items-center gap-2">
              <input
                type="range"
                min={11}
                max={18}
                step={1}
                value={shared.code_font_px ?? 13}
                onChange={(e) =>
                  setAppearance({
                    shared: { ...shared, code_font_px: Number(e.target.value) },
                  })
                }
              />
              <span className="w-8 text-right text-muted">{shared.code_font_px ?? 13}px</span>
            </span>
          </label>
        </div>
      </Section>
      <Section title="辅助显示">
        <div className="space-y-3 text-sm">
          <label className="flex items-center justify-between">
            对比度
            <select
              value={shared.contrast ?? "normal"}
              onChange={(e) =>
                setAppearance({
                  shared: { ...shared, contrast: e.target.value as "normal" | "high" },
                })
              }
              className="rounded-md border border-border bg-background px-2 py-1"
            >
              <option value="normal">正常</option>
              <option value="high">高对比</option>
            </select>
          </label>
          <label className="flex items-center justify-between">
            减弱动画
            <select
              value={appearance?.reduced_motion ?? "system"}
              onChange={(e) =>
                setAppearance({
                  reduced_motion: e.target.value as "system" | "on" | "off",
                })
              }
              className="rounded-md border border-border bg-background px-2 py-1"
            >
              <option value="system">跟随系统</option>
              <option value="on">开</option>
              <option value="off">关</option>
            </select>
          </label>
          <label className="flex items-center justify-between">
            差异标记
            <select
              value={appearance?.diff_markers ?? "color"}
              onChange={(e) =>
                setAppearance({
                  diff_markers: e.target.value as "color" | "symbols",
                })
              }
              className="rounded-md border border-border bg-background px-2 py-1"
            >
              <option value="color">颜色</option>
              <option value="symbols">符号（色盲友好）</option>
            </select>
          </label>
        </div>
      </Section>
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

  const CHANNEL_LABEL: Record<string, string> = {
    in_app: "应用内",
    email: "邮件",
    push: "推送",
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
          <ul className="space-y-3">
            {prefs.data.categories.map((cat) => (
              <li key={cat.id} className="text-sm">
                <div className="flex items-center justify-between">
                  <span>{cat.label}</span>
                  {!cat.available ? (
                    <span className="text-xs text-muted">{cat.reason}</span>
                  ) : null}
                </div>
                {cat.available ? (
                  <div className="mt-1 flex gap-2">
                    {cat.allowed_channels.map((ch) => {
                      const on = cat.selected_channels.includes(ch)
                      return (
                        <button
                          key={ch}
                          type="button"
                          aria-pressed={on}
                          disabled={saveChannels.isPending}
                          onClick={() =>
                            saveChannels.mutate({
                              category_id: cat.id,
                              selected_channels: on
                                ? cat.selected_channels.filter((c) => c !== ch)
                                : [...cat.selected_channels, ch],
                            })
                          }
                          className={
                            "rounded-full px-2.5 py-0.5 text-xs " +
                            (on
                              ? "bg-foreground text-background"
                              : "border border-border text-muted")
                          }
                        >
                          {CHANNEL_LABEL[ch] ?? ch}
                        </button>
                      )
                    })}
                  </div>
                ) : null}
              </li>
            ))}
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
  const archived = useQuery({
    queryKey: ["sessions", "archived"],
    queryFn: ({ signal }) => api.listSessions({ archived: "true", limit: 50 }, signal),
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
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  const items = archived.data?.sessions ?? []

  return (
    <Section title="已归档会话">
      {archived.isPending ? (
        <p className="text-sm text-muted">正在加载…</p>
      ) : archived.isError ? (
        <p role="alert" className="text-sm text-failure">
          {apiErrorText(archived.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted">没有已归档的会话</p>
      ) : (
        <ul className="space-y-1">
          {items.map((s) => {
            const status = s.last_run?.status ?? ""
            return (
              <li
                key={s.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
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
                  onClick={() => {
                    if (window.confirm("永久删除该会话？")) remove.mutate(s)
                  }}
                >
                  删除
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-failure">
          {error}
        </p>
      ) : null}
    </Section>
  )
}
