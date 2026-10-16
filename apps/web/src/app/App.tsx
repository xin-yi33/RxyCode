import { useEffect, type ReactNode } from "react"
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import { createBrowserRouter, Navigate, RouterProvider } from "react-router"

import { sessionVisualState } from "@desktop/sessionVisualState"
import { Button } from "../components/ui/button"
import { ChatPage } from "../features/chat/ChatPage"
import { OAuthCallbackPage, OnboardingPage } from "../features/onboarding/OnboardingPage"
import { createClient } from "../sdk/client"
import { useUi } from "../state/ui"

const api = createClient()
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

function Shell({ children }: { children: ReactNode }) {
  const theme = useUi((state) => state.theme)
  const setTheme = useUi((state) => state.setTheme)
  const setOffline = useUi((state) => state.setOffline)
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    document.documentElement.dataset.theme = theme
  }, [theme])
  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine)
    sync()
    window.addEventListener("online", sync)
    window.addEventListener("offline", sync)
    return () => {
      window.removeEventListener("online", sync)
      window.removeEventListener("offline", sync)
    }
  }, [setOffline])
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <p className="text-sm font-semibold">RxyCode</p>
        <Button
          variant="outline"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "浅色" : "深色"}
        </Button>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8">{children}</main>
    </div>
  )
}

function Status(props: {
  visual: string
  title: string
  detail: string
  onRetry?: () => void
}) {
  const alert = props.visual === "error" || props.visual === "disconnected"
  return (
    <section
      role={alert ? "alert" : "status"}
      data-visual={props.visual}
      className="rounded-lg border border-border bg-card p-6"
    >
      <h1 className="text-lg font-semibold">{props.title}</h1>
      <p className="mt-2 text-sm text-muted">{props.detail}</p>
      {props.onRetry ? (
        <Button className="mt-4" onClick={props.onRetry}>
          重试
        </Button>
      ) : null}
    </section>
  )
}

function LoginPage() {
  const offline = useUi((state) => state.offline)
  const theme = useUi((state) => state.theme)
  const query = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
  })
  const visual = sessionVisualState({
    loading: query.isPending,
    error: query.isError ? "API 未就绪" : null,
    empty: false,
    narrow: false,
    dark: theme === "dark",
  })
  if (offline) {
    return (
      <Shell>
        <Status
          visual="disconnected"
          title="连接已断开"
          detail="网络断开，登录请求停在当前页。"
          onRetry={() => void query.refetch()}
        />
      </Shell>
    )
  }
  if (visual === "loading") {
    return (
      <Shell>
        <Status visual="loading" title="正在加载" detail="正在确认登录状态。" />
      </Shell>
    )
  }
  if (visual === "error") {
    return (
      <Shell>
        <Status
          visual="error"
          title="API 未就绪"
          detail="登录接口没有响应，页面保持可见。"
          onRetry={() => void query.refetch()}
        />
      </Shell>
    )
  }
  return (
    <Shell>
      <Status visual={visual} title="已登录" detail={query.data?.user_id ?? ""} />
    </Shell>
  )
}

function ProjectsPage() {
  const offline = useUi((state) => state.offline)
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
  })
  const visual = sessionVisualState({
    loading: query.isPending,
    error: query.isError ? "API 未就绪" : null,
    empty: query.isSuccess && query.data.length === 0,
    narrow: false,
    dark: false,
  })
  if (offline) {
    return (
      <Shell>
        <Status
          visual="disconnected"
          title="连接已断开"
          detail="项目列表暂时不可用。"
          onRetry={() => void query.refetch()}
        />
      </Shell>
    )
  }
  if (visual === "loading") {
    return (
      <Shell>
        <Status visual="loading" title="正在加载" detail="正在读取项目。" />
      </Shell>
    )
  }
  if (visual === "error") {
    return (
      <Shell>
        <Status
          visual="error"
          title="API 未就绪"
          detail="项目接口没有响应。"
          onRetry={() => void query.refetch()}
        />
      </Shell>
    )
  }
  if (visual === "empty") {
    return (
      <Shell>
        <Status visual="empty" title="还没有项目" detail="当前账号下没有项目。" />
      </Shell>
    )
  }
  return (
    <Shell>
      <ul className="space-y-2">
        {query.data?.map((project) => (
          <li key={project.id} className="rounded-md border border-border bg-card px-3 py-2">
            {project.name}
          </li>
        ))}
      </ul>
    </Shell>
  )
}

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/onboarding", element: <OnboardingPage /> },
  { path: "/oauth/callback", element: <OAuthCallbackPage /> },
  { path: "/projects", element: <ProjectsPage /> },
  { path: "/runs/:runId", element: <ChatPage /> },
])

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
