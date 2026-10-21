import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient, type DeviceStatus, type Me } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useUi } from "../../state/ui"
import { useAuth, useLogout } from "../auth/useAuth"
import { ModelsSection } from "./ModelsSection"

const api = createClient()

const DEVICE_STATUS_TEXT: Record<string, string> = {
  active: "当前设备持有使用权",
  held_elsewhere: "另一台设备使用中",
  none: "—",
}

export function SettingsPage() {
  const theme = useUi((state) => state.theme)
  const toggleTheme = useUi((state) => state.toggleTheme)
  const me = useQuery<Me>({ queryKey: ["me"], enabled: false })
  const auth = useAuth()
  const queryClient = useQueryClient()
  const { logout, busy: logoutBusy, error: logoutError } = useLogout()
  // ?section=models 深链（Composer/错误提示跳转过来直接定位模型分区）。
  const [params] = useSearchParams()
  const section = params.get("section")

  // 安全区：单设备持有状态（GET /auth/device）。仅登录态查询。
  const device = useQuery<DeviceStatus>({
    queryKey: ["deviceStatus"],
    queryFn: ({ signal }) => api.getDeviceStatus(signal),
    enabled: auth.status === "authed",
    staleTime: 30_000,
  })
  const [claimBusy, setClaimBusy] = useState(false)
  const [claimError, setClaimError] = useState("")

  const claimDevice = () => {
    if (claimBusy) return
    setClaimBusy(true)
    setClaimError("")
    api
      .claimDevice()
      .then(() => void queryClient.invalidateQueries())
      .catch((err: unknown) => setClaimError(apiErrorText(err)))
      .finally(() => setClaimBusy(false))
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h2 className="text-lg font-semibold">设置</h2>
      <section className="mt-6 rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">外观</h3>
        <div className="mt-3 flex items-center justify-between text-sm">
          <span>主题：{theme === "dark" ? "深色" : "浅色"}</span>
          <Button variant="outline" size="sm" onClick={toggleTheme}>
            切换到{theme === "dark" ? "浅色" : "深色"}
          </Button>
        </div>
      </section>
      <div
        id="models"
        // 深链定位：滚动到模型分区。
        ref={(el) => {
          if (section === "models") el?.scrollIntoView()
        }}
        className="mt-4"
      >
        <h3 className="mb-3 text-sm font-medium">模型与 BYOK</h3>
        {auth.status === "authed" ? (
          <ModelsSection />
        ) : auth.status === "guest" ? (
          <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted">
            登录后可管理模型连接与自有模型（BYOK）。
          </p>
        ) : (
          <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted">
            正在确认登录状态…
          </p>
        )}
      </div>
      <section className="mt-4 rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">账号</h3>
        <dl className="mt-3 space-y-1 text-sm text-muted">
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
            <dt className="w-20 shrink-0">安全</dt>
            <dd className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                {device.isPending
                  ? "…"
                  : device.isError
                    ? "无法获取设备状态"
                    : (DEVICE_STATUS_TEXT[device.data?.status ?? ""] ??
                      device.data?.status ??
                      "—")}
              </span>
              {device.data?.status === "held_elsewhere" ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={claimBusy}
                  onClick={claimDevice}
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
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          disabled={logoutBusy}
          // 共享 useLogout：调 API → 清查询缓存 → SPA 回 /app；失败就地提示。
          onClick={() => void logout()}
        >
          {logoutBusy ? "退出中…" : "登出"}
        </Button>
        {logoutError ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {logoutError}
          </p>
        ) : null}
      </section>
    </div>
  )
}
