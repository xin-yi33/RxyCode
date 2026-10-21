import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link, NavLink, useLocation } from "react-router"

import {
  IconClose,
  IconLogout,
  IconPlus,
  IconSettings,
  IconUser,
} from "../../components/icons"
import { isAppPath, loginPathFor, safeNext } from "../../app/AuthGate"
import { usePopover } from "../../lib/usePopover"
import { createClient } from "../../sdk/client"
import { useUi } from "../../state/ui"
import { useAuth, useLogout } from "../auth/useAuth"
import { runStatusKind, runStatusText } from "../runs/status"

const api = createClient()

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

function SessionList() {
  const location = useLocation()
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  const auth = useAuth()
  const query = useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => api.listSessions(signal),
    refetchInterval: 15_000,
    // 访客不拉私有会话列表（PRD §3.2）。
    enabled: auth.status === "authed",
  })
  if (auth.status === "guest") {
    if (auth.unavailable) {
      return (
        <p role="alert" className="px-3 py-2 text-sm text-muted">
          无法确认登录状态{" "}
          <button type="button" className="underline" onClick={() => auth.refetch()}>
            重试
          </button>
        </p>
      )
    }
    return (
      <p className="px-3 py-2 text-sm text-muted">
        登录后查看历史会话{" "}
        <Link
          className="underline"
          to={loginPathFor(location.pathname, location.search)}
        >
          登录
        </Link>
      </p>
    )
  }
  if (query.isPending) {
    return <p className="px-3 py-2 text-sm text-muted">正在加载会话…</p>
  }
  if (query.isError) {
    return (
      <p role="alert" className="px-3 py-2 text-sm text-muted">
        会话列表暂不可用{" "}
        <button type="button" className="underline" onClick={() => void query.refetch()}>
          重试
        </button>
      </p>
    )
  }
  const sessions = query.data ?? []
  if (sessions.length === 0) {
    return <p className="px-3 py-2 text-sm text-muted">还没有会话</p>
  }
  return (
    <ul className="space-y-1 px-2 pb-4">
      {sessions.map((session) => {
        const status = session.last_run?.status ?? ""
        const active = location.pathname === `/app/s/${session.id}`
        return (
          <li key={session.id}>
            <NavLink
              to={`/app/s/${session.id}`}
              onClick={() => {
                if (window.matchMedia("(max-width: 767px)").matches) setSidebarOpen(false)
              }}
              className={
                "block rounded-md px-3 py-2 text-sm " +
                (active ? "bg-card font-medium" : "hover:bg-card/60")
              }
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate">{session.title || "未命名会话"}</span>
                {status ? (
                  <span
                    className={
                      "shrink-0 rounded-full px-2 py-0.5 text-xs " +
                      chipClass[runStatusKind(status)]
                    }
                  >
                    {runStatusText(status)}
                  </span>
                ) : null}
              </span>
            </NavLink>
          </li>
        )
      })}
    </ul>
  )
}

// 侧栏底部账户条：访客显示“未登录”，菜单只有 登录/注册；
// 登录态显示用户名，菜单为 设置/退出登录。Esc 或点击外部关闭。
function AccountMenu() {
  const location = useLocation()
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  const auth = useAuth()
  const { logout, busy: logoutBusy, error: logoutError } = useLogout()
  const [open, setOpen] = useState(false)
  const popRef = usePopover<HTMLDivElement>(open, () => setOpen(false))
  const name =
    auth.status === "authed"
      ? auth.user?.display_name || auth.user?.email || "账户"
      : auth.status === "pending"
        ? "账户"
        : "未登录"
  const next = safeNext(location.pathname + location.search)
  const closeOnMobile = () => {
    setOpen(false)
    if (window.matchMedia("(max-width: 767px)").matches) {
      setSidebarOpen(false)
    }
  }

  return (
    <div className="relative border-t border-border p-2" ref={popRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`账户：${name}`}
        className={
          "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left " +
          "text-sm hover:bg-card"
        }
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-border text-muted-ink">
          <IconUser size={15} />
        </span>
        <span className="min-w-0 flex-1 truncate">{name}</span>
      </button>
      {open ? (
        <div
          role="menu"
          className={
            "absolute bottom-full left-2 right-2 z-50 mb-1 overflow-hidden " +
            "rounded-lg border border-border bg-card shadow-md"
          }
        >
          {auth.status === "authed" ? (
            <>
              <NavLink
                to="/app/settings"
                state={{ from: location.pathname + location.search }}
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
                onClick={closeOnMobile}
              >
                <IconSettings size={15} />
                设置
              </NavLink>
              <button
                type="button"
                role="menuitem"
                disabled={logoutBusy}
                className={
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
                  "hover:bg-sidebar disabled:opacity-60"
                }
                // 失败时菜单保持打开，错误就地显示（不假称已退出）。
                onClick={logout}
              >
                <IconLogout size={15} />
                {logoutBusy ? "退出中…" : "登出"}
              </button>
              {logoutError ? (
                <p role="alert" className="px-3 pb-2 text-xs text-failure">
                  {logoutError}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <NavLink
                to={loginPathFor(location.pathname, location.search)}
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
                onClick={closeOnMobile}
              >
                <IconLogout size={15} />
                登录
              </NavLink>
              <NavLink
                to={isAppPath(next) ? `/register?next=${encodeURIComponent(next)}` : "/register"}
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
                onClick={closeOnMobile}
              >
                <IconPlus size={15} />
                注册
              </NavLink>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}

export function Sidebar() {
  const open = useUi((state) => state.sidebarOpen)
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="关闭会话列表"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      <aside
        aria-label="会话列表"
        className={
          "fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r " +
          "border-border bg-sidebar transition-transform md:static " +
          (open ? "translate-x-0" : "-translate-x-full") + " md:translate-x-0"
        }
      >
        <div className="flex items-center justify-between px-3 py-3">
          <Link to="/app" className="px-1 text-sm font-semibold tracking-tight">
            RxyCode
          </Link>
          <button
            type="button"
            aria-label="关闭会话列表"
            className="rounded-md p-1 text-muted hover:bg-card md:hidden"
            onClick={() => setSidebarOpen(false)}
          >
            <IconClose size={18} />
          </button>
        </div>
        <div className="px-2 pb-2">
          <Link
            to="/app"
            className={
              "flex items-center gap-2 rounded-md border border-border " +
              "bg-card px-3 py-2 text-sm font-medium hover:bg-background"
            }
          >
            <IconPlus size={16} />
            新任务
          </Link>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto">
          <SessionList />
        </nav>
        <AccountMenu />
      </aside>
    </>
  )
}
