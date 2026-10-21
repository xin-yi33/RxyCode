import { useEffect, useState, type ReactNode } from "react"
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider, useParams } from "react-router"

import { AuthGate, isAppPath, loginPathFor } from "./AuthGate"
import { appNavigate, registerNavigate } from "./nav"
import { ForgotPasswordPage } from "../features/auth/ForgotPasswordPage"
import { LoginPage } from "../features/auth/LoginPage"
import { ResetPasswordPage } from "../features/auth/ResetPasswordPage"
import { OAuthCallbackPage } from "../features/auth/OAuthCallbackPage"
import { RegisterPage } from "../features/auth/RegisterPage"
import { BrowserHandoff, handoffPageUrl } from "../features/browser/BrowserHandoff"
import { ConsoleShell } from "../features/console/ConsoleShell"
import { NewSessionPage } from "../features/console/NewSessionPage"
import { SessionPage } from "../features/console/SessionPage"
import { MemoryPage } from "../features/memory/MemoryPage"
import { RunHistoryRoute } from "../features/runs/RunHistoryRoute"
import { SchedulePage } from "../features/schedule/SchedulePage"
import { SettingsPage } from "../features/settings/SettingsPage"
import { TerminalPane } from "../features/terminal/TerminalPane"
import { UsagePage } from "../features/usage/UsagePage"
import { DiffReview } from "../features/workspace/DiffReview"
import { FileTree } from "../features/workspace/FileTree"
import { GitPanel } from "../features/workspace/GitPanel"
import { ApiError } from "../sdk/client"
import { useUi } from "../state/ui"

// Applies the persisted theme at the app root so auth pages follow it too.
function ThemeSync() {
  const theme = useUi((state) => state.theme)
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    document.documentElement.dataset.theme = theme
  }, [theme])
  return null
}

// W9-F1 + 访客入口：全局 401 处理改为 SPA 跳转（appNavigate →
// router.navigate），不整页刷新 —— 内存里的草稿随之保留。
// 例外：
//  - PUBLIC_PATHS 上的认证页不自跳（避免 /me 探测循环）。
//  - ["me"] 探测的 401 是“访客”语义，由 useAuth/AuthGate 就地解释。
//  - /app 内的 mutation 401 交给触发处（Composer 等）弹登录提示；
//    后台查询的 401 才直接跳（此时身份已失效，继续停留无意义）。
const PUBLIC_PATHS = new Set([
  "/login",
  "/register",
  "/forgot",
  "/reset",
  "/oauth/callback",
])

function redirectOn401() {
  const { pathname, search } = window.location
  if (PUBLIC_PATHS.has(pathname)) return
  appNavigate(loginPathFor(pathname, search), { replace: true })
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (!(error instanceof ApiError) || error.status !== 401) return
      if (query.queryKey[0] === "me") return // 公共身份探测：401 = 访客
      redirectOn401()
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      if (!(error instanceof ApiError) || error.status !== 401) return
      // /app 内由动作发起方弹“需要登录”层，保住上下文与草稿。
      if (isAppPath(window.location.pathname)) return
      redirectOn401()
    },
  }),
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

// "/" 永远进入 /app：访客先看壳与输入框，动作级再登录（PRD §3.2/E2E-01），
// 不再先探测身份 —— 不再有“确认登录中”的等待屏。
function RootRedirect() {
  return <Navigate to="/app" replace />
}

function WorkspacePage() {
  const { projectId = "" } = useParams()
  const [path, setPath] = useState("")
  const [draft, setDraft] = useState("")
  const [target, setTarget] = useState("")
  return (
    <main className="mx-auto min-h-screen max-w-5xl px-4 py-6">
      <p data-target={target}>{target}</p>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setPath(draft)
        }}
      >
        <label className="text-sm">
          路径
          <input
            className="ml-2 rounded-md border border-border px-2 py-1"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
        <button type="submit">打开</button>
      </form>
      <GitPanel projectId={projectId} />
      <FileTree projectId={projectId} onOpen={setPath} onTarget={setTarget} />
      <DiffReview projectId={projectId} path={path} />
    </main>
  )
}

function TerminalPage() {
  const { sessionId = "" } = useParams()
  return <TerminalPane sessionId={sessionId} />
}

function BrowserHandoffPage() {
  const { sessionId = "" } = useParams()
  return (
    <main>
      <a href={handoffPageUrl(sessionId)}>打开授权页</a>
      <BrowserHandoff sessionId={sessionId} authorized={false} />
    </main>
  )
}

function gated(element: ReactNode) {
  return <AuthGate>{element}</AuthGate>
}

const router = createBrowserRouter([
  { path: "/", element: <RootRedirect /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/forgot", element: <ForgotPasswordPage /> },
  { path: "/reset", element: <ResetPasswordPage /> },
  { path: "/oauth/callback", element: <OAuthCallbackPage /> },
  // Compatibility redirects — the console replaces these flows.
  { path: "/onboarding", element: <Navigate to="/app" replace /> },
  { path: "/projects", element: <Navigate to="/app" replace /> },
  {
    // /app 壳本身对访客开放：侧栏/顶栏/新任务输入框立即可见；
    // 会话详情与设置仍是私有子路由（AuthGate 就地拦截）。
    path: "/app",
    element: <ConsoleShell />,
    children: [
      { index: true, element: <NewSessionPage /> },
      { path: "s/:sessionId", element: gated(<SessionPage />) },
      { path: "settings", element: gated(<SettingsPage />) },
    ],
  },
  {
    path: "/runs/:runId",
    element: gated(<ConsoleShell />),
    children: [{ index: true, element: <RunHistoryRoute /> }],
  },
  // Legacy pages kept behind auth until W10.
  { path: "/usage", element: gated(<UsagePage />) },
  { path: "/projects/:projectId/memory", element: gated(<MemoryPage />) },
  { path: "/projects/:projectId/schedule", element: gated(<SchedulePage />) },
  { path: "/projects/:projectId/workspace", element: gated(<WorkspacePage />) },
  { path: "/terminal/:sessionId", element: gated(<TerminalPage />) },
  { path: "/browser/:sessionId", element: gated(<BrowserHandoffPage />) },
])

// React 树之外（query cache 回调、SSE 恢复链）统一走 SPA 导航。
registerNavigate((to, opts) => {
  void router.navigate(to, opts)
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeSync />
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
