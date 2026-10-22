import { useQuery } from "@tanstack/react-query"
import { useLocation, useParams } from "react-router"

import { IconConsole, IconMenu, IconMoon, IconSun } from "../../components/icons"
import { createClient } from "../../sdk/client"
import { useApplyAppearance, usePatchPreferences, usePreferences } from "../../state/prefs"
import { useUi } from "../../state/ui"

const api = createClient()

export function Topbar() {
  const location = useLocation()
  const params = useParams()
  const toggleSidebar = useUi((state) => state.toggleSidebar)
  const consoleOpen = useUi((state) => state.consoleOpen)
  const toggleConsole = useUi((state) => state.toggleConsole)

  const prefs = usePreferences()
  const patch = usePatchPreferences()
  useApplyAppearance(prefs.data)
  const mode = prefs.data?.appearance.mode ?? "system"

  const sessionId = params.sessionId ?? ""
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: ({ signal }) => api.getSession(sessionId, signal),
    enabled: sessionId.length > 0,
  })
  const projectId = params.projectId ?? ""
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => api.getProject(projectId, signal),
    enabled: projectId.length > 0,
  })

  let title = "新任务"
  if (location.pathname.startsWith("/settings")) title = "设置"
  else if (location.pathname === "/scheduled" || location.pathname === "/app/scheduled")
    title = "定时任务"
  else if (location.pathname === "/plugins") title = "插件"
  else if (projectId) title = project.data?.project.name ?? "项目"
  else if (sessionId) title = session.data?.title ?? "会话"

  const cycleTheme = () => {
    const next = mode === "dark" ? "light" : "dark"
    patch.mutate(
      { appearance: { mode: next }, expected_revision: prefs.data?.revision },
      { onError: () => undefined },
    )
  }

  return (
    <header className="rxy-app-topbar flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
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
        aria-label={mode === "dark" ? "切换到浅色" : "切换到深色"}
        title={mode === "dark" ? "切换到浅色" : "切换到深色"}
        className="rounded-md p-1.5 text-muted hover:bg-sidebar"
        onClick={cycleTheme}
      >
        {mode === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </button>
    </header>
  )
}
