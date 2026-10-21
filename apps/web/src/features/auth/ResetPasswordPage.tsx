import { useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get("token") ?? ""
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    if (password !== confirm) {
      setError("两次输入的密码不一致")
      return
    }
    setBusy(true)
    setError("")
    api
      .resetPassword({ token, password })
      .then(() => setDone(true))
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  return (
    <AuthLayout>
      {done ? (
        <div className="space-y-4">
          <p className="text-lg font-semibold">密码已重置</p>
          <p className="text-sm text-muted">所有已登录会话均已退出，请用新密码登录。</p>
          <Button className="w-full" onClick={() => window.location.assign("/login")}>
            去登录
          </Button>
        </div>
      ) : !token ? (
        <div className="space-y-4">
          <p className="text-lg font-semibold">链接无效</p>
          <p className="text-sm text-muted">重置链接缺少参数，请重新发起。</p>
          <p className="text-sm text-muted">
            <Link className="text-foreground underline" to="/forgot">
              重新发送重置链接
            </Link>
          </p>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm font-medium">
            新密码
            <input
              className={inputClass}
              type="password"
              name="password"
              autoComplete="new-password"
              required
              minLength={8}
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <label className="block text-sm font-medium">
            确认新密码
            <input
              className={inputClass}
              type="password"
              name="confirm"
              autoComplete="new-password"
              required
              minLength={8}
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </label>
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "正在重置…" : "重置密码"}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}
