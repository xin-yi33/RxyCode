import { useState, type ReactNode } from "react"
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
import { SettingsShell } from "../features/settings/SettingsShell"
import { SchedulesPage } from "../features/schedule/SchedulesPage"
import { ProjectPage } from "../features/projects/ProjectPage"
import { PluginsPage } from "../features/plugins/PluginsPage"
import { TerminalPane } from "../features/terminal/TerminalPane"
import { UsagePage } from "../features/usage/UsagePage"
import { DiffReview } from "../features/workspace/DiffReview"
import { FileTree } from "../features/workspace/FileTree"
import { GitPanel } from "../features/workspace/GitPanel"
import { ApiError } from "../sdk/client"
import { useUi } from "../state/ui"
import { I18nProvider } from "../lib/i18n"
import { localeSettingFromPrefs, useApplyAppearance, usePreferences } from "../state/prefs"

// Applies server-driven appearance (theme/fonts/contrast/motion/diff) at the
// app root so auth pages follow it too; guests fall back to the rxy_theme
// cookie. Locale likewise resolves prefs → rxy_locale cookie → navigator.
function PreferenceSync({ children }: { children: ReactNode }) {
  const prefs = usePreferences()
  useApplyAppearance(prefs.data)
  return <I18nProvider setting={localeSettingFromPrefs(prefs.data)}>{children}</I18nProvider>
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

// 409 DEVICE_IN_USE 是全局模态（不跳转）：置 Zustand 位，ConsoleShell 顶层的
// <DeviceConflictModal> 渲染“在此设备继续使用”。mutation 的 isAppPath 早退
// 只管 401，设备冲突一律先到这里 —— /app 内的写操作同样弹层。
function raiseDeviceConflict(error: unknown): boolean {
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    error.code === "DEVICE_IN_USE"
  ) {
    useUi.getState().setDeviceConflict(true)
    return true
  }
  return false
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (raiseDeviceConflict(error)) return
      if (!(error instanceof ApiError) || error.status !== 401) return
      if (query.queryKey[0] === "me") return // 公共身份探测：401 = 访客
      redirectOn401()
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      if (raiseDeviceConflict(error)) return
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

// /app/settings?section=models 旧深链 → /settings/models；未知 section 落 general。
const SETTINGS_SECTIONS = new Set([
  "general",
  "appearance",
  "notifications",
  "security",
  "archived",
  "models",
])

function LegacySettingsRedirect() {
  const params = new URLSearchParams(window.location.search)
  const section = params.get("section") ?? "general"
  const target = SETTINGS_SECTIONS.has(section) ? section : "general"
  return <Navigate to={`/settings/${target}`} replace />
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
      { path: "p/:projectId", element: gated(<ProjectPage />) },
      { path: "scheduled", element: gated(<SchedulesPage />) },
      // /app/settings?section=x 深链兼容 → /settings/:section。
      { path: "settings", element: <LegacySettingsRedirect /> },
      { path: "settings/:section", element: <LegacySettingsRedirect /> },
    ],
  },
  {
    // 顶层 /settings/:section 走同一控制台壳（规格 UI-2026-10-22 §01）。
    path: "/settings",
    element: gated(<ConsoleShell />),
    children: [
      { index: true, element: <Navigate to="general" replace /> },
      { path: ":section", element: <SettingsShell /> },
    ],
  },
  {
    path: "/scheduled",
    element: gated(<ConsoleShell />),
    children: [{ index: true, element: <SchedulesPage /> }],
  },
  {
    path: "/plugins",
    element: gated(<ConsoleShell />),
    children: [{ index: true, element: <PluginsPage /> }],
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
      <PreferenceSync>
        <RouterProvider router={router} />
      </PreferenceSync>
    </QueryClientProvider>
  )
}
