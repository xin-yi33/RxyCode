import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient, type Me } from "../../sdk/client"
import { useUi } from "../../state/ui"

const api = createClient()

export function SettingsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const theme = useUi((state) => state.theme)
  const toggleTheme = useUi((state) => state.toggleTheme)
  const me = useQuery<Me>({ queryKey: ["me"], enabled: false })

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
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
        </dl>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => {
            void api
              .logout()
              .catch(() => undefined)
              .then(() => {
                queryClient.clear()
                navigate("/login", { replace: true })
              })
          }}
        >
          登出
        </Button>
      </section>
    </div>
  )
}
