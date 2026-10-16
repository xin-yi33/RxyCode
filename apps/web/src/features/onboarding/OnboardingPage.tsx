import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { useSearchParams } from "react-router"

import { useLocalLogin } from "../auth/useLocalLogin"
import { ProjectPanel } from "../projects/ProjectPanel"
import { ApiError, createClient } from "../../sdk/client"
import { journeyState } from "./journey"

type Mode = "local" | "cloud" | "remote"

export function OnboardingPage() {
  const client = useMemo(() => createClient(), [])
  const [mode, setMode] = useState<Mode | null>(null)
  const [secret, setSecret] = useState("")
  const login = useLocalLogin()
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => client.getMe(signal),
    retry: false,
  })
  const loggedOut = me.isError && me.error instanceof ApiError && me.error.status === 401
  const journey = journeyState(mode, me.isSuccess)
  return (
    <main className="mx-auto min-h-screen max-w-3xl bg-background px-4 py-6 text-foreground">
      <h1 className="text-xl font-semibold">选择运行位置</h1>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="rounded-md border border-border px-3 py-2" onClick={() => setMode("local")}>
          本地
        </button>
        <button type="button" className="rounded-md border border-border px-3 py-2" onClick={() => setMode("cloud")}>
          云端
        </button>
        <button type="button" className="rounded-md border border-border px-3 py-2" onClick={() => setMode("remote")}>
          远程
        </button>
      </div>
      <section
        className="mt-4 text-sm"
        data-journey=""
        data-permission={journey.permission}
        data-target={journey.target}
        data-status={journey.status}
      >
        <p>当前权限 {journey.permission || "未授予"}</p>
        <p>执行目标 {journey.target || "未选择"}</p>
      </section>
      {mode === "local" ? <p className="mt-4 text-sm">本机回环，不需要 GitHub 账户。</p> : null}
      {mode === "cloud" ? (
        <div className="mt-4 grid gap-3">
          <p className="text-sm">云端必须完成 GitHub 授权。未授权的 OAuth 会被拒绝。</p>
          <button
            type="button"
            className="rounded-md border border-border px-3 py-2 text-sm"
            onClick={() => {
              void client.githubStart().then((row) => {
                window.location.assign(row.authorization_url)
              })
            }}
          >
            使用 GitHub
          </button>
        </div>
      ) : null}
      {mode === "remote" ? (
        <p className="mt-4 text-sm">远程 Runner 沿用当前身份，不新建公网账户。</p>
      ) : null}
      {me.isPending ? <p className="mt-4">正在加载</p> : null}
      {me.isError && !loggedOut ? (
        <p role="alert" className="mt-4">
          无法连接
          <button type="button" className="ml-3 underline" onClick={() => void me.refetch()}>
            重试
          </button>
        </p>
      ) : null}
      {loggedOut && mode === "local" ? (
        <form
          className="mt-4 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            login.mutate(secret, { onSuccess: () => void me.refetch() })
          }}
        >
          <label className="grid gap-1 text-sm">
            本机口令
            <input
              type="password"
              className="rounded-md border border-border bg-card px-3 py-2"
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
            />
          </label>
          <button type="submit" className="rounded-md bg-foreground px-3 py-2 text-sm text-background">
            登录
          </button>
          {login.isError ? <p role="alert">登录失败</p> : null}
        </form>
      ) : null}
      {me.isSuccess ? <ProjectPanel /> : null}
    </main>
  )
}

export function OAuthCallbackPage() {
  const client = useMemo(() => createClient(), [])
  const [params] = useSearchParams()
  const state = params.get("state") ?? ""
  const code = params.get("code") ?? ""
  const callback = useQuery({
    queryKey: ["github-callback", state, code],
    queryFn: () => client.finishGithub(state, code),
    retry: false,
  })
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      {callback.isPending ? <p>正在加载</p> : null}
      {callback.isError ? <p role="alert">授权失败</p> : null}
      {callback.isSuccess ? <p>已登录</p> : null}
    </main>
  )
}
