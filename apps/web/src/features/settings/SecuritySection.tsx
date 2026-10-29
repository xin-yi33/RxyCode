import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { Button } from "../../components/ui/button"
import {
  createClient,
  type AuthSessionItem,
  type PasskeyItem,
  type SecurityEventItem,
} from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { useAuth } from "../auth/useAuth"

const api = createClient()

// base64url helpers for WebAuthn ceremonies.
function b64urlToBuffer(value: string): ArrayBuffer {
  const pad = "=".repeat((4 - (value.length % 4)) % 4)
  const b64 = (value + pad).replace(/-/g, "+").replace(/_/g, "/")
  const raw = atob(b64)
  const buf = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
  return buf.buffer
}

function bufferToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let raw = ""
  for (const b of bytes) raw += String.fromCharCode(b)
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// Reauth 小模态：敏感操作前先拿 reauth_token。
function ReauthDialog({
  purpose,
  onToken,
  onClose,
}: {
  purpose: string
  onToken: (token: string) => void
  onClose: () => void
}) {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const mutation = useMutation({
    mutationFn: () => api.reauthenticate({ method: "password", purpose, password }),
    onSuccess: (data) => onToken(data.reauth_token),
    onError: (err) => setError(apiErrorText(err)),
  })
  // 表单弹层 maskClosable=false：遮罩点击不关闭，关闭走「取消」按钮 / Esc。
  // Esc 挂 document：点过遮罩后焦点回落 body，overlay onKeyDown 收不到。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="重新验证身份"
    >
      <form
        className="w-full max-w-sm rounded-xl border border-border bg-card p-4 shadow-xl"
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <h3 className="text-sm font-semibold">重新验证身份</h3>
        <p className="mt-1 text-xs text-muted">此操作需要确认你的密码。</p>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="账户密码"
          className="mt-3 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        />
        {error ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <div className="mt-3 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" disabled={!password || mutation.isPending}>
            {mutation.isPending ? "验证中…" : "验证"}
          </Button>
        </div>
      </form>
    </div>
  )
}

// ---- TOTP 注册流：setup → 展示 secret/otpauth → confirm → backup codes -----

function TotpSetup({ token, onDone }: { token: string; onDone: () => void }) {
  const [step, setStep] = useState<"init" | "confirm" | "codes">("init")
  const [setup, setSetup] = useState<{ setup_id: string; otpauth_uri: string; secret: string } | null>(null)
  const [code, setCode] = useState("")
  const [codes, setCodes] = useState<string[]>([])
  const [error, setError] = useState("")

  const start = useMutation({
    mutationFn: () => api.totpSetup(token),
    onSuccess: (data) => {
      setSetup(data)
      setStep("confirm")
    },
    onError: (err) => setError(apiErrorText(err)),
  })
  const confirm = useMutation({
    mutationFn: () => api.totpConfirm(setup!.setup_id, code.trim()),
    onSuccess: (data) => {
      setCodes(data.backup_codes)
      setStep("codes")
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  return (
    <div className="rounded-lg border border-border p-3">
      {step === "init" ? (
        <Button size="sm" disabled={start.isPending} onClick={() => start.mutate()}>
          {start.isPending ? "生成中…" : "开始绑定 TOTP"}
        </Button>
      ) : step === "confirm" && setup ? (
        <div className="space-y-2 text-sm">
          <p>在认证器中添加此密钥（或打开 URI）：</p>
          <code className="block break-all rounded bg-background p-2 text-xs">{setup.secret}</code>
          <code className="block break-all rounded bg-background p-2 text-xs">{setup.otpauth_uri}</code>
          <div className="flex items-center gap-2">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="6 位验证码"
              inputMode="numeric"
              autoComplete="one-time-code"
              className="w-32 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
            <Button size="sm" disabled={code.trim().length < 6 || confirm.isPending} onClick={() => confirm.mutate()}>
              确认绑定
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2 text-sm">
          <p className="font-medium">保存这些恢复码（仅显示一次）：</p>
          <ul className="grid grid-cols-2 gap-1">
            {codes.map((c) => (
              <li key={c}>
                <code className="rounded bg-background px-2 py-0.5 text-xs">{c}</code>
              </li>
            ))}
          </ul>
          <Button size="sm" onClick={onDone}>
            我已保存
          </Button>
        </div>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-failure">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function SecuritySection() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [error, setError] = useState("")
  const [reauth, setReauth] = useState<{ purpose: string; then: (t: string) => void } | null>(null)
  const [totpToken, setTotpToken] = useState<string | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [newPassword2, setNewPassword2] = useState("")
  const [pwMsg, setPwMsg] = useState("")

  const overview = useQuery({
    queryKey: ["security-overview"],
    queryFn: ({ signal }) => api.getSecurityOverview(signal),
    enabled: auth.status === "authed",
  })
  const passkeys = useQuery({
    queryKey: ["passkeys"],
    queryFn: ({ signal }) => api.listPasskeys(signal),
    enabled: auth.status === "authed",
  })
  const sessions = useQuery({
    queryKey: ["auth-sessions"],
    queryFn: ({ signal }) => api.listAuthSessions(signal),
    enabled: auth.status === "authed",
  })
  const events = useQuery({
    queryKey: ["security-events"],
    queryFn: ({ signal }) => api.listSecurityEvents(signal),
    enabled: auth.status === "authed",
  })

  const refresh = () => void queryClient.invalidateQueries()
  const needReauth = (purpose: string, then: (t: string) => void) =>
    setReauth({ purpose, then })

  const changePassword = useMutation({
    mutationFn: (token: string) =>
      api.changePassword({ new_password: newPassword, reauth_token: token }),
    onSuccess: () => {
      setPwMsg("密码已更新")
      setNewPassword("")
      setNewPassword2("")
      refresh()
    },
    onError: (err) => setPwMsg(apiErrorText(err)),
  })

  const doRegisterPasskey = async (token: string) => {
    setError("")
    try {
      // options → navigator.credentials.create → verify
      const optionsResp = await fetch("/api/v1/auth/passkeys/registration/options", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reauth_token: token }),
      })
      if (!optionsResp.ok) throw new Error(await optionsResp.text())
      const opts = (await optionsResp.json()) as {
        challenge_id: string
        challenge: string
        user: { id: string }
      } & Record<string, unknown>
      // Convert challenge/user.id to ArrayBuffer.
      const publicKey = {
        ...opts,
        challenge: b64urlToBuffer(opts.challenge),
        user: {
          ...(opts.user as object),
          id: b64urlToBuffer(opts.user.id),
        },
      } as unknown as PublicKeyCredentialCreationOptions
      const credential = (await navigator.credentials.create({
        publicKey,
      })) as PublicKeyCredential | null
      if (!credential) throw new Error("已取消")
      const response = credential.response as AuthenticatorAttestationResponse
      const verify = await fetch("/api/v1/auth/passkeys/registration/verify", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          challenge_id: opts.challenge_id,
          credential: {
            id: credential.id,
            rawId: bufferToB64url(credential.rawId),
            type: credential.type,
            response: {
              clientDataJSON: bufferToB64url(response.clientDataJSON),
              attestationObject: bufferToB64url(response.attestationObject),
            },
          },
        }),
      })
      if (!verify.ok) throw new Error(await verify.text())
      refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败")
    }
  }

  const revokeSession = useMutation({
    mutationFn: ({ id, token }: { id: string; token: string }) =>
      api.revokeAuthSession(id, token),
    onSuccess: refresh,
    onError: (err) => setError(apiErrorText(err)),
  })
  const revokeAll = useMutation({
    mutationFn: (token: string) =>
      api.revokeAllAuthSessions({ reauth_token: token, include_current: false }),
    onSuccess: refresh,
    onError: (err) => setError(apiErrorText(err)),
  })
  const deleteTotp = useMutation({
    mutationFn: ({ token, code }: { token: string; code: string }) =>
      api.totpDelete(token, code),
    onSuccess: refresh,
    onError: (err) => setError(apiErrorText(err)),
  })
  const regenCodes = useMutation({
    mutationFn: (token: string) => api.regenRecoveryCodes(token),
    onSuccess: (data) => {
      window.alert(`新的恢复码（仅显示一次）：\n${data.backup_codes.join("\n")}`)
      refresh()
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  const o = overview.data

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">安全概览</h3>
        {overview.isPending ? (
          <p className="mt-2 text-sm text-muted">正在加载…</p>
        ) : o ? (
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm text-muted sm:grid-cols-3">
            <div>通行密钥：{o.passkeys_count}</div>
            <div>TOTP：{o.totp_enabled ? "已启用" : "未启用"}</div>
            <div>活跃会话：{o.active_sessions_count}</div>
            <div>已授权应用：{o.authorized_apps_count}</div>
            <div>密码：{o.password_present ? "已设置" : "未设置"}</div>
          </dl>
        ) : null}
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">修改密码</h3>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="新密码（8-128 位）"
            className="w-48 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
          <input
            type="password"
            value={newPassword2}
            onChange={(e) => setNewPassword2(e.target.value)}
            placeholder="再次输入"
            className="w-48 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
          <Button
            size="sm"
            disabled={newPassword.length < 8 || newPassword !== newPassword2}
            onClick={() => needReauth("password_change", (t) => changePassword.mutate(t))}
          >
            更新密码
          </Button>
        </div>
        {pwMsg ? <p className="mt-2 text-xs text-muted">{pwMsg}</p> : null}
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">通行密钥（Passkey）</h3>
        {passkeys.isPending ? (
          <p className="mt-2 text-sm text-muted">正在加载…</p>
        ) : passkeys.data && !passkeys.data.capability.available ? (
          <p className="mt-2 text-sm text-muted">{passkeys.data.capability.reason}</p>
        ) : (
          <>
            <ul className="mt-2 space-y-1">
              {(passkeys.data?.passkeys ?? []).map((k: PasskeyItem) => (
                <li key={k.id} className="flex justify-between rounded-md border border-border px-3 py-2 text-sm">
                  <span>{k.name || "通行密钥"}</span>
                  <span className="text-xs text-muted">注册于 {fmt(k.created_at)}</span>
                </li>
              ))}
            </ul>
            <Button
              className="mt-2"
              variant="outline"
              size="sm"
              onClick={() => needReauth("passkey_add", (t) => void doRegisterPasskey(t))}
            >
              注册通行密钥
            </Button>
          </>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">两步验证（TOTP）</h3>
        {o?.totp_enabled ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">已启用</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => needReauth("recovery_codes", (t) => regenCodes.mutate(t))}
            >
              重新生成恢复码
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const code = window.prompt("输入当前 TOTP 验证码以解绑：")
                if (code) needReauth("totp_remove", (t) => deleteTotp.mutate({ token: t, code }))
              }}
            >
              解绑
            </Button>
          </div>
        ) : totpToken ? (
          <div className="mt-2">
            <TotpSetup
              token={totpToken}
              onDone={() => {
                setTotpToken(null)
                refresh()
              }}
            />
          </div>
        ) : (
          <Button
            className="mt-2"
            variant="outline"
            size="sm"
            onClick={() => needReauth("totp_setup", (t) => setTotpToken(t))}
          >
            绑定 TOTP
          </Button>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">登录会话</h3>
          <Button
            variant="outline"
            size="sm"
            onClick={() => needReauth("session_revoke", (t) => revokeAll.mutate(t))}
          >
            退出其他设备
          </Button>
        </div>
        {sessions.isPending ? (
          <p className="mt-2 text-sm text-muted">正在加载…</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {(sessions.data?.sessions ?? []).map((s: AuthSessionItem) => (
              <li key={s.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate">
                    {s.device_label || "未知设备"}
                    {s.current ? <span className="ml-2 text-xs text-success-ink">（当前）</span> : null}
                  </p>
                  <p className="text-xs text-muted">
                    {s.ip_hint} · 最近活动 {fmt(s.last_seen_at)}
                  </p>
                </div>
                {!s.current ? (
                  <button
                    type="button"
                    className="shrink-0 text-xs text-failure underline"
                    onClick={() => needReauth("session_revoke", (t) => revokeSession.mutate({ id: s.id, token: t }))}
                  >
                    退出
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium">安全事件</h3>
        {events.isPending ? (
          <p className="mt-2 text-sm text-muted">正在加载…</p>
        ) : (events.data?.events ?? []).length === 0 ? (
          <p className="mt-2 text-sm text-muted">暂无事件</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {(events.data?.events ?? []).map((e: SecurityEventItem) => (
              <li key={e.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                <span>
                  {e.type}
                  <span className="ml-2 text-xs text-muted">{e.result}</span>
                </span>
                <span className="text-xs text-muted">{fmt(e.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {error ? (
        <p role="alert" className="text-sm text-failure">
          {error}
        </p>
      ) : null}
      {reauth ? (
        <ReauthDialog
          purpose={reauth.purpose}
          onToken={(t) => {
            setReauth(null)
            reauth.then(t)
          }}
          onClose={() => setReauth(null)}
        />
      ) : null}
    </div>
  )
}
