import { useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient, type Me } from "../../sdk/client"
import { apiErrorText, isNetworkError, isUnauthorized } from "../../sdk/errors"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

function usePostLoginTarget(): string {
  const [params] = useSearchParams()
  const next = params.get("next") ?? ""
  return next.startsWith("/app") ? next : "/app"
}

export function LoginPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const target = usePostLoginTarget()
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: ({ signal }) => api.getCapabilities(signal),
    staleTime: 60_000,
  })
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
    retry: false,
    staleTime: 30_000,
  })
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [localSecret, setLocalSecret] = useState("")
  const [showLocal, setShowLocal] = useState(false)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const finish = (body: Me) => {
    queryClient.setQueryData(["me"], body)
    navigate(target, { replace: true })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    api
      .login(email.trim().toLowerCase(), password)
      .then(finish)
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  const submitLocal = (event: FormEvent) => {
    event.preventDefault()
    if (busy || !localSecret) return
    setBusy(true)
    setError("")
    api
      .localLogin(localSecret)
      .then(() => api.getMe())
      .then(finish)
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  if (me.isSuccess) return <Navigate to={target} replace />
  // A down API still shows a recoverable state, not a fake "logged out" page.
  if (me.isError && !isUnauthorized(me.error)) {
    return (
      <AuthLayout>
        <div role="alert">
          <p className="text-lg font-semibold">无法连接服务器</p>
          <p className="mt-2 text-sm text-muted">登录状态无法确认，请稍后重试。</p>
          <Button className="mt-4" onClick={() => void me.refetch()}>
            重试
          </Button>
        </div>
      </AuthLayout>
    )
  }

  const github = capabilities.data?.github === true
  const local = capabilities.data?.local === true
  const passwordLogin = capabilities.data?.password !== false

  return (
    <AuthLayout>
      {passwordLogin ? (
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm font-medium">
            邮箱
            <input
              className={inputClass}
              type="email"
              name="email"
              autoComplete="email"
              required
              autoFocus
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="block text-sm font-medium">
            密码
            <input
              className={inputClass}
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "正在登录…" : "登录"}
          </Button>
        </form>
      ) : null}
      <p className="mt-4 text-center text-sm text-muted">
        没有账号？{" "}
        <Link className="text-foreground underline" to="/register">
          注册
        </Link>
      </p>
      {github ? (
        <div className="mt-4 border-t border-border pt-4">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              void api.githubStart().then((body) => {
                window.location.assign(body.authorization_url)
              })
            }}
          >
            使用 GitHub 继续
          </Button>
        </div>
      ) : null}
      {local ? (
        <div className="mt-4 border-t border-border pt-4">
          <button
            type="button"
            className="text-sm text-muted underline"
            onClick={() => setShowLocal((open) => !open)}
            aria-expanded={showLocal}
          >
            本机口令
          </button>
          {showLocal ? (
            <form onSubmit={submitLocal} className="mt-2 space-y-2">
              <label className="block text-sm font-medium">
                本机口令
                <input
                  className={inputClass}
                  type="password"
                  name="local-secret"
                  autoComplete="off"
                  value={localSecret}
                  onChange={(event) => setLocalSecret(event.target.value)}
                />
              </label>
              <Button type="submit" variant="outline" className="w-full" disabled={busy}>
                使用本机口令登录
              </Button>
            </form>
          ) : null}
        </div>
      ) : null}
      {capabilities.isError && isNetworkError(capabilities.error) ? (
        <p className="mt-4 text-center text-sm text-muted">
          部分登录方式暂不可用（无法连接服务器）
        </p>
      ) : null}
    </AuthLayout>
  )
}
