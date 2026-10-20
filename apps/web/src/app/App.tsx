import { useEffect, useState, type ReactNode } from "react"
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider, useParams } from "react-router"

import { AuthGate, loginPathFor } from "./AuthGate"
import { LoginPage } from "../features/auth/LoginPage"
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
import { ApiError, createClient } from "../sdk/client"
import { useUi } from "../state/ui"

const api = createClient()

// Applies the persisted theme at the app root so auth pages follow it too.
function ThemeSync() {
  const theme = useUi((state) => state.theme)
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    document.documentElement.dataset.theme = theme
  }, [theme])
  return null
}

// W9-F1: one global 401 path. Any authed-page query/mutation that gets a 401
// sends the user to /login?next=… (only /app… paths are allowed as next).
// Auth pages are excluded so a logged-out /me probe does not loop.
const PUBLIC_PATHS = new Set(["/login", "/register", "/oauth/callback"])

function redirectOn401() {
  if (PUBLIC_PATHS.has(window.location.pathname)) return
  window.location.assign(
    loginPathFor(window.location.pathname, window.location.search),
  )
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) redirectOn401()
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) redirectOn401()
    },
  }),
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

// "/" sends the user to /app when authenticated and /login otherwise.
function RootRedirect() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
  })
  if (me.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <p role="status" className="text-sm text-muted">
          正在确认登录状态…
        </p>
      </main>
    )
  }
  if (me.isSuccess) return <Navigate to="/app" replace />
  if (me.isError && me.error instanceof ApiError && me.error.status !== 401) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <section role="alert" className="w-full max-w-sm rounded-lg border border-border bg-card p-6">
          <h1 className="text-lg font-semibold">无法连接服务器</h1>
          <p className="mt-2 text-sm text-muted">服务端暂不可用，稍后重试。</p>
        </section>
      </main>
    )
  }
  return <Navigate to="/login" replace />
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
  { path: "/oauth/callback", element: <OAuthCallbackPage /> },
  // Compatibility redirects — the console replaces these flows.
  { path: "/onboarding", element: <Navigate to="/app" replace /> },
  { path: "/projects", element: <Navigate to="/app" replace /> },
  {
    path: "/app",
    element: gated(<ConsoleShell />),
    children: [
      { index: true, element: <NewSessionPage /> },
      { path: "s/:sessionId", element: <SessionPage /> },
      { path: "settings", element: <SettingsPage /> },
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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeSync />
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
