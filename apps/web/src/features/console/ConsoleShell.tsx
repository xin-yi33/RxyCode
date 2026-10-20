import { useEffect } from "react"
import { Outlet } from "react-router"

import { useUi } from "../../state/ui"
import { ConsolePanel } from "./ConsolePanel"
import { Sidebar } from "./Sidebar"
import { Topbar } from "./Topbar"

// W9-F2 console shell: persistent sidebar + topbar + page outlet + optional
// bottom console panel. Theme/offline side effects live here so they apply to
// every /app page.
export function ConsoleShell() {
  const consoleOpen = useUi((state) => state.consoleOpen)
  const setOffline = useUi((state) => state.setOffline)
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)

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

  // The sidebar starts closed on narrow screens, open on desktop.
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)")
    const sync = () => setSidebarOpen(!query.matches)
    sync()
    query.addEventListener("change", sync)
    return () => query.removeEventListener("change", sync)
  }, [setSidebarOpen])

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div className="flex min-h-0 min-w-0 flex-1">
          <main id="main" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <Outlet />
          </main>
          {/* ≥1280px：400px 右侧栏；以下由面板自身 fixed inset-0 全屏覆盖。 */}
          {consoleOpen ? <ConsolePanel /> : null}
        </div>
      </div>
    </div>
  )
}
