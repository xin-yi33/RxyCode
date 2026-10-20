import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useLocation, useNavigate, useParams } from "react-router"

import { IconConsole, IconLogout, IconMenu, IconMoon, IconSun } from "../../components/icons"
import { createClient, type Me } from "../../sdk/client"
import { useUi } from "../../state/ui"

const api = createClient()

export function Topbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()
  const queryClient = useQueryClient()
  const theme = useUi((state) => state.theme)
  const toggleTheme = useUi((state) => state.toggleTheme)
  const toggleSidebar = useUi((state) => state.toggleSidebar)
  const consoleOpen = useUi((state) => state.consoleOpen)
  const toggleConsole = useUi((state) => state.toggleConsole)

  const me = useQuery<Me>({ queryKey: ["me"], enabled: false })
  const sessionId = params.sessionId ?? ""
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: ({ signal }) => api.getSession(sessionId, signal),
    enabled: sessionId.length > 0,
  })

  let title = "新任务"
  if (location.pathname === "/app/settings") title = "设置"
  else if (sessionId) title = session.data?.title ?? "会话"

  const logout = () => {
    void api
      .logout()
      .catch(() => undefined)
      .then(() => {
        queryClient.clear()
        navigate("/login", { replace: true })
      })
  }

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
      <button
        type="button"
        aria-label="打开会话列表"
        className="rounded-md p-1.5 text-muted hover:bg-sidebar md:hidden"
        onClick={toggleSidebar}
      >
        <IconMenu size={18} />
      </button>
      <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{title}</h1>
      <button
        type="button"
        aria-label={consoleOpen ? "关闭控制台" : "打开控制台"}
        aria-pressed={consoleOpen}
        title={consoleOpen ? "关闭控制台" : "打开控制台"}
        className="rounded-md p-1.5 text-muted hover:bg-sidebar"
        onClick={toggleConsole}
      >
        <IconConsole size={18} />
      </button>
      <button
        type="button"
        aria-label={theme === "dark" ? "切换到浅色" : "切换到深色"}
        title={theme === "dark" ? "切换到浅色" : "切换到深色"}
        className="rounded-md p-1.5 text-muted hover:bg-sidebar"
        onClick={toggleTheme}
      >
        {theme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </button>
      <span className="hidden max-w-40 truncate text-xs text-muted sm:block">
        {me.data?.user?.email ?? me.data?.user?.display_name ?? ""}
      </span>
      <button
        type="button"
        aria-label="登出"
        title="登出"
        className="rounded-md p-1.5 text-muted hover:bg-sidebar"
        onClick={logout}
      >
        <IconLogout size={18} />
      </button>
    </header>
  )
}
