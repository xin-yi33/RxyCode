import { useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, Navigate, useNavigate } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText, isUnauthorized } from "../../sdk/errors"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

export function RegisterPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
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
  const [invite, setInvite] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const registration = capabilities.data?.registration ?? "invite"

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    api
      .register({
        email: email.trim().toLowerCase(),
        password,
        ...(registration === "invite" ? { invite_code: invite.trim() } : {}),
      })
      .then((body) => {
        queryClient.setQueryData(["me"], body)
        navigate("/app", { replace: true })
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  if (me.isSuccess) return <Navigate to="/app" replace />
  if (me.isError && !isUnauthorized(me.error)) {
    return (
      <AuthLayout>
        <div role="alert">
          <p className="text-lg font-semibold">无法连接服务器</p>
          <p className="mt-2 text-sm text-muted">注册状态无法确认，请稍后重试。</p>
          <Button className="mt-4" onClick={() => void me.refetch()}>
            重试
          </Button>
        </div>
      </AuthLayout>
    )
  }

  if (registration === "closed") {
    return (
      <AuthLayout>
        <p className="text-center text-lg font-semibold">暂未开放注册</p>
        <p className="mt-4 text-center text-sm text-muted">
          已有账号？{" "}
          <Link className="text-foreground underline" to="/login">
            登录
          </Link>
        </p>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
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
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <span className="mt-1 block text-xs text-muted">至少 8 位</span>
        </label>
        {registration === "invite" ? (
          <label className="block text-sm font-medium">
            邀请码
            <input
              className={inputClass}
              type="text"
              name="invite-code"
              autoComplete="off"
              required
              value={invite}
              onChange={(event) => setInvite(event.target.value)}
            />
          </label>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-failure">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "正在注册…" : "注册"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        已有账号？{" "}
        <Link className="text-foreground underline" to="/login">
          登录
        </Link>
      </p>
    </AuthLayout>
  )
}
