// 身份探测（访客入口的核心）：公共 /me 探测的 401 只是“访客”，
// 不是错误；5xx/网络错误是 unavailable —— 不能当成登出（PRD §3.2）。
import { useCallback, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router"

import { createClient, resetCsrfCache, type Me } from "../../sdk/client"
import { apiErrorText, isUnauthorized } from "../../sdk/errors"
import { useUi } from "../../state/ui"

const api = createClient()

export type AuthStatus = "pending" | "authed" | "guest"

export type AuthState = {
  status: AuthStatus
  user: Me["user"] | null
  me: Me | null
  // 非 401 的探测失败（网络/5xx）：界面应显示“无法确认”，而非访客态。
  unavailable: boolean
  refetch: () => void
}

export function useAuth(): AuthState {
  const query = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
    staleTime: 60_000,
    retry: false,
  })
  const unavailable = query.isError && !isUnauthorized(query.error)
  const status: AuthStatus = query.isPending
    ? "pending"
    : query.isSuccess
      ? "authed"
      : "guest"
  return {
    status,
    user: query.data?.user ?? null,
    me: query.data ?? null,
    unavailable,
    refetch: () => void query.refetch(),
  }
}

// 统一的退出路径（NAV-09 / SET-08）：成功后清掉私有缓存与全部草稿回
// 访客壳 /app；失败留在原地并给出内联错误，不假装已退出。
export function useLogout(): { logout: () => void; busy: boolean; error: string } {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const resetDrafts = useUi((state) => state.resetDrafts)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const wipe = useCallback(() => {
    queryClient.clear()
    resetCsrfCache()
    resetDrafts()
  }, [queryClient, resetDrafts])

  const logout = useCallback(() => {
    if (busy) return
    setBusy(true)
    setError("")
    api
      .logout()
      .then(() => {
        // 先导航再清缓存：被门控的页面卸载后再 wipe，避免 AuthGate 竞态
        // 把用户送去 /login 而不是访客壳 /app。
        navigate("/app", { replace: true })
        window.setTimeout(wipe, 0)
      })
      .catch((err: unknown) => {
        if (isUnauthorized(err)) {
          // 服务端会话已经没了 —— 视为已退出，本地照常清理。
          navigate("/app", { replace: true })
          window.setTimeout(wipe, 0)
          return
        }
        setError(apiErrorText(err))
      })
      .finally(() => setBusy(false))
  }, [busy, navigate, wipe])

  return { logout, busy, error }
}
