import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Navigate, useLocation } from "react-router"

import { Button } from "../components/ui/button"
import { createClient } from "../sdk/client"
import { isUnauthorized } from "../sdk/errors"

const api = createClient()

// Only in-app paths may be forwarded as the post-login target.
export function safeNext(pathname: string): string {
  return pathname.startsWith("/app") ? pathname : "/app"
}

export function loginPathFor(pathname: string, search = ""): string {
  const next = safeNext(pathname + (pathname.startsWith("/app") ? search : ""))
  return `/login?next=${encodeURIComponent(next)}`
}

export function AuthGate({ children }: { children: ReactNode }) {
  const location = useLocation()
  const query = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
    staleTime: 30_000,
  })

  if (query.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <p role="status" className="text-sm text-muted">
          正在确认登录状态…
        </p>
      </main>
    )
  }
  if (query.isError) {
    if (isUnauthorized(query.error)) {
      return <Navigate to={loginPathFor(location.pathname, location.search)} replace />
    }
    // Network/5xx must not be rendered as "not logged in".
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <section role="alert" className="w-full max-w-sm rounded-lg border border-border bg-card p-6">
          <h1 className="text-lg font-semibold">无法连接服务器</h1>
          <p className="mt-2 text-sm text-muted">服务端暂不可用，稍后重试。</p>
          <Button className="mt-4" onClick={() => void query.refetch()}>
            重试
          </Button>
        </section>
      </main>
    )
  }
  return <>{children}</>
}
