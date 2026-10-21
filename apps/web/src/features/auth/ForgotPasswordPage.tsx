import { useState, type FormEvent } from "react"
import { Link } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [devLink, setDevLink] = useState("")

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    api
      .forgotPassword(email.trim().toLowerCase())
      .then((body) => {
        setSent(true)
        setDevLink(body.reset_url ?? "")
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  return (
    <AuthLayout>
      {sent ? (
        <div className="space-y-4">
          <p className="text-lg font-semibold">重置邮件已发送</p>
          <p className="text-sm text-muted">
            如果该邮箱已注册，你会在几分钟内收到一封带重置链接的邮件（30 分钟内有效）。
          </p>
          {devLink ? (
            <p className="rounded-md border border-border bg-sidebar p-3 text-sm">
              开发模式：{" "}
              <a className="text-foreground underline break-all" href={devLink}>
                点击直接重置密码
              </a>
            </p>
          ) : null}
          <p className="text-sm text-muted">
            <Link className="text-foreground underline" to="/login">
              返回登录
            </Link>
          </p>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm text-muted">输入注册邮箱，我们会发送密码重置链接。</p>
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
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "正在发送…" : "发送重置链接"}
          </Button>
          <p className="text-center text-sm text-muted">
            <Link className="text-foreground underline" to="/login">
              返回登录
            </Link>
          </p>
        </form>
      )}
    </AuthLayout>
  )
}
