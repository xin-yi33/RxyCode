import { useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient, type Me } from "../../sdk/client"
import { apiErrorText, isNetworkError, isUnauthorized } from "../../sdk/errors"
import { AltchaWidget } from "./AltchaWidget"
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
  const [code, setCode] = useState("")
  const [localSecret, setLocalSecret] = useState("")
  const [showLocal, setShowLocal] = useState(false)
  const [loginMode, setLoginMode] = useState<"password" | "code">("password")
  const [captcha, setCaptcha] = useState("")
  const [captchaKey, setCaptchaKey] = useState(0)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  const finish = (body: Me) => {
    queryClient.setQueryData(["me"], body)
    navigate(target, { replace: true })
  }

  const refreshCaptcha = () => {
    setCaptcha("")
    setCaptchaKey((k) => k + 1)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    api
      .login({
        email: email.trim().toLowerCase(),
        ...(loginMode === "code" ? { code: code.trim() } : { password }),
        captcha,
      })
      .then(finish)
      .catch((err: unknown) => {
        setError(apiErrorText(err))
        refreshCaptcha()
      })
      .finally(() => setBusy(false))
  }

  const sendCode = () => {
    if (sending || cooldown > 0) return
    setSending(true)
    setError("")
    api
      .requestLoginCode({ email: email.trim().toLowerCase(), captcha })
      .then((body) => {
        setNotice(
          body.delivery === "operator-log"
            ? "验证码已生成，请联系管理员从服务器日志获取。"
            : "验证码已发送（如该邮箱已注册），15 分钟内有效。",
        )
        setCooldown(60)
        const timer = setInterval(() => {
          setCooldown((s) => {
            if (s <= 1) clearInterval(timer)
            return s - 1
          })
        }, 1000)
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => {
        setSending(false)
        refreshCaptcha()
      })
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
  const codeLogin = (capabilities.data?.code_delivery ?? "none") !== "none"
  const wantsCaptcha = capabilities.data?.captcha === "altcha"
  const emailReady = /.+@.+\..+/.test(email.trim())
  const canSend = emailReady && (!wantsCaptcha || !!captcha) && cooldown === 0
  const canSubmit =
    !!email.trim() &&
    (loginMode === "password" ? !!password : code.trim().length === 6) &&
    (!wantsCaptcha || !!captcha)

  return (
    <AuthLayout>
      {passwordLogin ? (
        <form onSubmit={submit} className="space-y-4">
          {codeLogin ? (
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-border p-1 text-sm">
              {(["password", "code"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  className={
                    "rounded-md py-1.5 transition-colors " +
                    (loginMode === m
                      ? "bg-sidebar font-medium text-foreground"
                      : "text-muted hover:text-foreground")
                  }
                  onClick={() => setLoginMode(m)}
                >
                  {m === "password" ? "密码登录" : "验证码登录"}
                </button>
              ))}
            </div>
          ) : null}
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
          {loginMode === "password" ? (
            <label className="block text-sm font-medium">
              <span className="flex items-baseline justify-between">
                密码
                {capabilities.data?.password_reset === true ? (
                  <Link className="text-xs font-normal text-muted underline" to="/forgot">
                    忘记密码？
                  </Link>
                ) : null}
              </span>
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
          ) : (
            <label className="block text-sm font-medium">
              邮箱验证码
              <div className="mt-1 flex gap-2">
                <input
                  className={inputClass + " mt-0 min-w-0 flex-1"}
                  type="text"
                  name="login-code"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="6 位数字"
                  autoComplete="one-time-code"
                  required
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                />
                <Button
                  type="button"
                  variant="outline"
                  className="shrink-0 whitespace-nowrap"
                  disabled={!canSend || sending}
                  onClick={sendCode}
                >
                  {cooldown > 0 ? `${cooldown}s 后重发` : sending ? "发送中…" : "发送验证码"}
                </Button>
              </div>
            </label>
          )}
          {wantsCaptcha ? (
            <div className="pt-1">
              <AltchaWidget key={captchaKey} onVerify={setCaptcha} />
            </div>
          ) : null}
          {notice ? <p className="text-sm text-muted">{notice}</p> : null}
          {error ? (
            <p role="alert" className="text-sm text-failure">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy || !canSubmit}>
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
