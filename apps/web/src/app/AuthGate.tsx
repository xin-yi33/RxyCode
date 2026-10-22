import type { ReactNode } from "react"
import { Navigate, useLocation, useSearchParams } from "react-router"

import { Button } from "../components/ui/button"
import { useAuth } from "../features/auth/useAuth"

// 只允许白名单的站内控制台路径作为登录后回跳目标 —— 必须跟
// "/"、"?"、"#" 或恰好结尾，否则 "/apple" 之类的路径会漏进来。
// /settings/*、/scheduled、/plugins 等新增路由同样允许续接（UI-2026-10-22 §01）。
const APP_PATH_RE = /^\/(app|settings|scheduled|plugins|runs|usage|projects|terminal|browser|memory)(?:[/?#]|$)/

export function isAppPath(path: string): boolean {
  return APP_PATH_RE.test(path)
}

export function safeNext(pathname: string): string {
  return APP_PATH_RE.test(pathname) ? pathname : "/app"
}

export function loginPathFor(pathname: string, search = ""): string {
  const next = safeNext(pathname + (APP_PATH_RE.test(pathname) ? search : ""))
  return `/login?next=${encodeURIComponent(next)}`
}

// 认证页共用的回跳解析：?next= 只认 /app 站内路径。
export function useSafeNext(fallback = "/app"): string {
  const [params] = useSearchParams()
  const next = params.get("next") ?? ""
  return APP_PATH_RE.test(next) ? next : fallback
}

// 私有路由门：pending 显示确认中；401 → SPA 跳登录（草稿存活于内存
// Zustand，SPA 导航不丢）；5xx/断网 → 可重试错误卡片，不冒充登出。
export function AuthGate({ children }: { children: ReactNode }) {
  const location = useLocation()
  const auth = useAuth()

  if (auth.status === "pending") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <p role="status" className="text-sm text-muted">
          正在确认登录状态…
        </p>
      </main>
    )
  }
  if (auth.status === "guest") {
    if (!auth.unavailable) {
      return <Navigate to={loginPathFor(location.pathname, location.search)} replace />
    }
    // Network/5xx must not be rendered as "not logged in".
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <section role="alert" className="w-full max-w-sm rounded-lg border border-border bg-card p-6">
          <h1 className="text-lg font-semibold">无法连接服务器</h1>
          <p className="mt-2 text-sm text-muted">服务端暂不可用，稍后重试。</p>
          <Button className="mt-4" onClick={() => auth.refetch()}>
            重试
          </Button>
        </section>
      </main>
    )
  }
  return <>{children}</>
}
