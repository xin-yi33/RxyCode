import { useQuery } from "@tanstack/react-query"

import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useAuth } from "../auth/useAuth"

const api = createClient()

// /plugins 路由壳（UI-2026-10-22 §01）：展示可用插件/能力；插件宿主在
// appserver 侧，Web 面只读列出模型连接暴露的能力。
export function PluginsPage() {
  const auth = useAuth()
  const models = useQuery({
    queryKey: ["models-catalog"],
    queryFn: ({ signal }) => api.listModels(signal),
    enabled: auth.status === "authed",
  })

  if (auth.status !== "authed") {
    return <p className="px-6 py-8 text-sm text-muted">登录后查看可用能力。</p>
  }
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h2 className="text-lg font-semibold">插件与能力</h2>
      <p className="mt-1 text-sm text-muted">
        插件宿主运行在本地 runtime；此处列出当前可用的模型能力。
      </p>
      {models.isPending ? (
        <p className="mt-4 text-sm text-muted">正在加载…</p>
      ) : models.isError ? (
        <p role="alert" className="mt-4 text-sm text-failure">
          {apiErrorText(models.error)}
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {(models.data?.models ?? []).map((m) => (
            <li
              key={m.model_ref}
              className="rounded-lg border border-border bg-card px-4 py-3 text-sm"
            >
              {m.display_name || m.model_ref}
              {m.provider_name ? (
                <span className="ml-2 text-xs text-muted">{m.provider_name}</span>
              ) : null}
            </li>
          ))}
          {(models.data?.models ?? []).length === 0 ? (
            <li className="text-sm text-muted">暂无可用模型</li>
          ) : null}
        </ul>
      )}
    </div>
  )
}
