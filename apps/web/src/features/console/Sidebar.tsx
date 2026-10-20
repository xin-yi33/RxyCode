import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, NavLink, useLocation, useNavigate } from "react-router"

import {
  IconClose,
  IconLogout,
  IconPlus,
  IconSettings,
  IconUser,
} from "../../components/icons"
import { createClient, type Me } from "../../sdk/client"
import { useUi } from "../../state/ui"
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
  const query = useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => api.listSessions(signal),
    refetchInterval: 15_000,
  })
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

// 侧栏底部账户条：头像 + 邮箱/昵称，点开弹出“设置 / 登出”。
function AccountMenu() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  const [open, setOpen] = useState(false)
  // 只读 AuthGate 已填充的 ["me"] 缓存；enabled:false + 真 queryFn 避免
  // “No queryFn” 噪音，也保证缓存过期后能补拉。
  const me = useQuery<Me>({
    queryKey: ["me"],
    queryFn: ({ signal }) => api.getMe(signal),
    enabled: false,
    staleTime: 30_000,
  })
  const name =
    me.data?.user?.display_name || me.data?.user?.email || "账户"

  const logout = () => {
    setOpen(false)
    void api
      .logout()
      .catch(() => undefined)
      .then(() => {
        queryClient.clear()
        navigate("/login", { replace: true })
      })
  }

  return (
    <div className="relative border-t border-border p-2">
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
        <>
          <button
            type="button"
            aria-label="关闭账户菜单"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div
            role="menu"
            className={
              "absolute bottom-full left-2 right-2 z-50 mb-1 overflow-hidden " +
              "rounded-lg border border-border bg-card shadow-md"
            }
          >
            <NavLink
              to="/app/settings"
              role="menuitem"
              className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
              onClick={() => {
                setOpen(false)
                if (window.matchMedia("(max-width: 767px)").matches) {
                  setSidebarOpen(false)
                }
              }}
            >
              <IconSettings size={15} />
              设置
            </NavLink>
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-sidebar"
              onClick={logout}
            >
              <IconLogout size={15} />
              登出
            </button>
          </div>
        </>
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
