import { useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, Navigate, useNavigate } from "react-router"

import { useSafeNext } from "../../app/AuthGate"
import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText, isUnauthorized } from "../../sdk/errors"
import { AltchaWidget } from "./AltchaWidget"
import { AuthLayout } from "./AuthLayout"

const api = createClient()

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm " +
  "text-foreground outline-none focus:border-muted"

export function RegisterPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // 注册成功回到发起处（访客从 /app 触发登录/注册时带 ?next=）。
  const target = useSafeNext("/app")
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: ({ signal }) => api.getCapabilities(signal),
    staleTime: 60_000,
  })
  const capabilitiesReady = capabilities.data !== undefined
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
    retry: false,
    staleTime: 30_000,
  })
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [invite, setInvite] = useState("")
  const [code, setCode] = useState("")
  const [captcha, setCaptcha] = useState("")
  const [captchaKey, setCaptchaKey] = useState(0)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  const registration = capabilities.data?.registration ?? "invite"
  const needsCode = (capabilities.data?.code_delivery ?? "none") !== "none"
  const wantsCaptcha = capabilities.data?.captcha === "altcha"
  const emailReady = /.+@.+\..+/.test(email.trim())
  const canSend =
    capabilitiesReady && emailReady && (!wantsCaptcha || !!captcha) && cooldown === 0
  const canSubmit =
    capabilitiesReady &&
    !!email.trim() && password.length >= 8 && (!needsCode || code.trim().length === 6) &&
    (!wantsCaptcha || !!captcha)

  const refreshCaptcha = () => {
    setCaptcha("")
    setCaptchaKey((k) => k + 1)
  }

  const sendCode = () => {
    if (!capabilitiesReady) {
      setError(
        capabilities.isError
          ? "无法确认验证码配置，请重试后再发送。"
          : "正在确认验证码配置，请稍候后再试。",
      )
      return
    }
    if (sending || !canSend) return
    setSending(true)
    setError("")
    api
      .requestRegisterCode({ email: email.trim().toLowerCase(), captcha })
      .then((body) => {
        setNotice(
          body.delivery === "operator-log"
            ? "验证码已生成，请联系管理员从服务器日志获取。"
            : "验证码已发送到邮箱（如已注册则不会收到），15 分钟内有效。",
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
        refreshCaptcha() // captcha is single-use — remount for the register submit
      })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!capabilitiesReady) {
      setError(
        capabilities.isError
          ? "无法确认验证码配置，请重试后再注册。"
          : "正在确认验证码配置，请稍候后再试。",
      )
      return
    }
    if (busy || !canSubmit) return
    setBusy(true)
    setError("")
    api
      .register({
        email: email.trim().toLowerCase(),
        password,
        ...(registration === "invite" ? { invite_code: invite.trim() } : {}),
        ...(needsCode ? { code: code.trim() } : {}),
        captcha,
      })
      .then((body) => {
        queryClient.setQueryData(["me"], body)
        navigate(target, { replace: true })
      })
      .catch((err: unknown) => {
        setError(apiErrorText(err))
        refreshCaptcha()
      })
      .finally(() => setBusy(false))
  }

  if (me.isSuccess) return <Navigate to={target} replace />
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
          <Link
            className="text-foreground underline"
            to={`/login?next=${encodeURIComponent(target)}`}
          >
            登录
          </Link>
        </p>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      {!capabilitiesReady ? (
        <div
          role={capabilities.isError ? "alert" : "status"}
          className="mb-4 text-center text-sm text-muted"
        >
          <p>
            {capabilities.isError
              ? "无法确认验证码配置，请检查网络后重试。"
              : "正在确认验证码配置，请稍候。"}
          </p>
          {capabilities.isError ? (
            <Button
              type="button"
              variant="outline"
              className="mt-2"
              disabled={capabilities.isFetching}
              onClick={() => void capabilities.refetch()}
            >
              {capabilities.isFetching ? "重试中…" : "重试"}
            </Button>
          ) : null}
        </div>
      ) : null}
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
        {needsCode ? (
          <label className="block text-sm font-medium">
            邮箱验证码
            <div className="mt-1 flex gap-2">
              <input
                className={inputClass + " mt-0 min-w-0 flex-1"}
                type="text"
                name="email-code"
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
        ) : null}
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
        <Button
          type="submit"
          className="w-full"
          disabled={!capabilitiesReady || busy || !canSubmit}
        >
          {busy ? "正在注册…" : "注册"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        已有账号？{" "}
        <Link
          className="text-foreground underline"
          to={`/login?next=${encodeURIComponent(target)}`}
        >
          登录
        </Link>
      </p>
      <p className="mt-2 text-center text-xs">
        <Link className="text-muted underline" to={target}>
          返回应用
        </Link>
      </p>
    </AuthLayout>
  )
}
