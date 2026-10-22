import { useEffect } from "react"
import { Outlet, useLocation } from "react-router"

import { recordAppPath } from "../../lib/lastAppPath"
import { useUi } from "../../state/ui"
import { useMobileViewport } from "../../lib/useMobileViewport"
import { DeviceConflictModal } from "../devices/DeviceConflictModal"
import { SearchModal } from "../search/SearchModal"
import { ConsolePanel } from "./ConsolePanel"
import { Sidebar } from "./Sidebar"
import { Topbar } from "./Topbar"

// W9-F2 console shell: persistent sidebar + topbar + page outlet + optional
// bottom console panel. Theme/offline side effects live here so they apply to
// every /app page.
export function ConsoleShell() {
  useMobileViewport()
  const location = useLocation()
  const consoleOpen = useUi((state) => state.consoleOpen)
  const setOffline = useUi((state) => state.setOffline)
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)

  // SET-01「返回应用」记录最后一个应用内位置（/settings 自身不计入）。
  useEffect(() => {
    recordAppPath(location.pathname, location.search)
  }, [location.pathname, location.search])

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
    <div className="rxy-app-shell flex h-screen min-h-0 overflow-hidden bg-background text-foreground">
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
      {/* 409 DEVICE_IN_USE 全局模态（queryClient.onError 置位后渲染）。 */}
      <DeviceConflictModal />
      {/* Ctrl+K 全局搜索（UI-2026-10-22 §02）。 */}
      <SearchModal />
      <ToastHost />
    </div>
  )
}

/** 轻量 toast —— “链接已复制”等一次性提示，3s 自动消退（SES-05）。 */
function ToastHost() {
  const toast = useUi((state) => state.toast)
  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => useUi.setState({ toast: null }), 3000)
    return () => window.clearTimeout(timer)
  }, [toast])
  if (!toast) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 left-1/2 z-[80] -translate-x-1/2 rounded-md border border-border bg-card px-3 py-2 text-sm shadow-md"
    >
      {toast.text}
    </div>
  )
}
