import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, NavLink, useLocation, useNavigate } from "react-router"

import {
  IconCalendar,
  IconClose,
  IconLogout,
  IconMenu,
  IconPlus,
  IconSearch,
  IconSettings,
  IconUser,
} from "../../components/icons"
import { isAppPath, loginPathFor, safeNext } from "../../app/AuthGate"
import { useI18n } from "../../lib/i18n"
import { usePopover } from "../../lib/usePopover"
import { createClient, type Project, type SessionListItem } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
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

function isMobileViewport() {
  return window.matchMedia("(max-width: 767px)").matches
}

// ---- 会话条目菜单：重命名/置顶/归档/移动/删除 -----------------------------

function SessionMenu({
  session,
  projects,
  onClose,
}: {
  session: SessionListItem
  projects: Project[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { t } = useI18n()
  const [error, setError] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [title, setTitle] = useState(session.title)
  const popRef = usePopover<HTMLDivElement>(true, onClose)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["sessions"] })
  }
  const fail = (err: unknown) => setError(apiErrorText(err))

  const rename = useMutation({
    mutationFn: () =>
      api.patchSession(session.id, {
        title: title.trim(),
        expected_revision: session.revision,
      }),
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: fail,
  })

  const togglePin = useMutation({
    mutationFn: () =>
      api.patchSession(session.id, {
        pinned: !session.pinned,
        expected_revision: session.revision,
      }),
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: fail,
  })

  const toggleArchive = useMutation({
    mutationFn: () =>
      session.archived
        ? api.unarchiveSession(session.id, { expected_revision: session.revision })
        : api.archiveSession(session.id, { expected_revision: session.revision }),
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: fail,
  })

  const move = useMutation({
    mutationFn: (projectId: string) =>
      api.patchSession(session.id, {
        project_id: projectId,
        expected_revision: session.revision,
      }),
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: fail,
  })

  const del = useMutation({
    mutationFn: () =>
      api.deleteSession(session.id, {
        expected_revision: session.revision,
        confirm: true,
      }),
    onSuccess: () => {
      invalidate()
      onClose()
      navigate("/app")
    },
    onError: fail,
  })

  const busy =
    rename.isPending || togglePin.isPending || toggleArchive.isPending || move.isPending || del.isPending

  const item = (label: string, onClick: () => void, danger = false) => (
    <button
      type="button"
      role="menuitem"
      disabled={busy}
      onClick={onClick}
      className={
        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
        "hover:bg-sidebar disabled:opacity-60 " +
        (danger ? "text-failure" : "")
      }
    >
      {label}
    </button>
  )

  return (
    <div
      ref={popRef}
      role="menu"
      className={
        "absolute right-0 top-full z-50 mt-1 w-52 overflow-hidden rounded-lg " +
        "border border-border bg-card shadow-md"
      }
    >
      {renameOpen ? (
        <div className="p-2">
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && title.trim()) rename.mutate()
              if (e.key === "Escape") setRenameOpen(false)
            }}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            aria-label={t("session.rename")}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" className="text-xs text-muted" onClick={() => setRenameOpen(false)}>
              {t("app.cancel")}
            </button>
            <button
              type="button"
              className="text-xs font-medium"
              disabled={!title.trim() || busy}
              onClick={() => rename.mutate()}
            >
              {t("app.save")}
            </button>
          </div>
        </div>
      ) : moveOpen ? (
        <div className="max-h-56 overflow-y-auto py-1">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              role="menuitem"
              disabled={busy || project.id === session.project_id}
              onClick={() => move.mutate(project.id)}
              className={
                "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
                "hover:bg-sidebar disabled:opacity-50"
              }
            >
              {project.name}
              {project.id === session.project_id ? " ✓" : ""}
            </button>
          ))}
        </div>
      ) : confirmDelete ? (
        <div className="p-3">
          <p className="text-xs text-muted">{t("session.deleteConfirm")}</p>
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" className="text-xs text-muted" onClick={() => setConfirmDelete(false)}>
              {t("app.cancel")}
            </button>
            <button
              type="button"
              className="text-xs font-medium text-failure"
              disabled={busy}
              onClick={() => del.mutate()}
            >
              {t("app.delete")}
            </button>
          </div>
        </div>
      ) : (
        <>
          {item(t("session.rename"), () => setRenameOpen(true))}
          {item(session.pinned ? t("session.unpin") : t("session.pin"), () => togglePin.mutate())}
          {item(t("session.moveTo"), () => setMoveOpen(true))}
          {item(
            session.archived ? t("session.unarchive") : t("session.archive"),
            () => toggleArchive.mutate(),
          )}
          {item(t("session.delete"), () => setConfirmDelete(true), true)}
        </>
      )}
      {error ? (
        <p role="alert" className="px-3 py-2 text-xs text-failure">
          {error}
        </p>
      ) : null}
    </div>
  )
}

function SessionRow({ session, projects }: { session: SessionListItem; projects: Project[] }) {
  const location = useLocation()
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  const [menuOpen, setMenuOpen] = useState(false)
  const status = session.last_run?.status ?? ""
  const active = location.pathname === `/app/s/${session.id}`
  return (
    <li className="group relative">
      <NavLink
        to={`/app/s/${session.id}`}
        onClick={() => {
          if (isMobileViewport()) setSidebarOpen(false)
        }}
        className={
          "block rounded-md px-3 py-2 pr-8 text-sm " +
          (active ? "bg-card font-medium" : "hover:bg-card/60")
        }
      >
        <span className="flex items-center justify-between gap-2">
          <span className="truncate">
            {session.title || "未命名会话"}
            {session.archived ? (
              <span className="ml-1 text-xs text-muted">（已归档）</span>
            ) : null}
          </span>
          {status ? (
            <span className={"shrink-0 rounded-full px-2 py-0.5 text-xs " + chipClass[runStatusKind(status)]}>
              {runStatusText(status)}
            </span>
          ) : null}
        </span>
      </NavLink>
      <button
        type="button"
        aria-label="会话操作"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
        className={
          "absolute right-1 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 " +
          "text-muted opacity-0 hover:bg-sidebar focus:opacity-100 " +
          "group-hover:opacity-100 " +
          (menuOpen ? "opacity-100" : "")
        }
      >
        ⋯
      </button>
      {menuOpen ? (
        <SessionMenu session={session} projects={projects} onClose={() => setMenuOpen(false)} />
      ) : null}
    </li>
  )
}

// ---- 会话列表（pinned / recent 分区） -------------------------------------

function SessionSections({ projects }: { projects: Project[] }) {
  const location = useLocation()
  const auth = useAuth()
  const { t } = useI18n()
  const query = useQuery({
    queryKey: ["sessions", "sidebar"],
    queryFn: ({ signal }) => api.listSessions({ archived: "false", limit: 50 }, signal),
    refetchInterval: 15_000,
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
        <Link className="underline" to={loginPathFor(location.pathname, location.search)}>
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
  const sessions = query.data?.sessions ?? []
  if (sessions.length === 0) {
    return <p className="px-3 py-2 text-sm text-muted">{t("app.noSessions")}</p>
  }
  const pinned = sessions
    .filter((s) => s.pinned)
    .sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0))
  const recent = sessions.filter((s) => !s.pinned)
  return (
    <div className="pb-4">
      {pinned.length ? (
        <>
          <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted">
            {t("app.pinned")}
          </p>
          <ul className="space-y-1 px-2">
            {pinned.map((session) => (
              <SessionRow key={session.id} session={session} projects={projects} />
            ))}
          </ul>
        </>
      ) : null}
      {recent.length ? (
        <>
          <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted">
            {t("app.recent")}
          </p>
          <ul className="space-y-1 px-2">
            {recent.map((session) => (
              <SessionRow key={session.id} session={session} projects={projects} />
            ))}
          </ul>
        </>
      ) : null}
    </div>
  )
}

function ProjectSection() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [error, setError] = useState("")
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
    enabled: auth.status === "authed",
  })
  const create = useMutation({
    mutationFn: () => api.createProjectEx({ name: name.trim() }),
    onSuccess: () => {
      setCreating(false)
      setName("")
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  if (auth.status !== "authed") return null
  const projects = (query.data ?? []).filter((p) => !p.is_default)
  return (
    <div className="pb-2">
      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">
          {t("app.projects")}
        </p>
        <button
          type="button"
          aria-label="新建项目"
          className="rounded p-0.5 text-muted hover:bg-card"
          onClick={() => setCreating((v) => !v)}
        >
          <IconPlus size={14} />
        </button>
      </div>
      {creating ? (
        <div className="px-3 pb-2">
          <input
            autoFocus
            value={name}
            placeholder="项目名称"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) create.mutate()
              if (e.key === "Escape") setCreating(false)
            }}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
          {error ? (
            <p role="alert" className="mt-1 text-xs text-failure">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
      {projects.length ? (
        <ul className="space-y-1 px-2">
          {projects.map((project) => (
            <li key={project.id}>
              <NavLink
                to={`/app/p/${project.id}`}
                className={({ isActive }) =>
                  "block truncate rounded-md px-3 py-1.5 text-sm " +
                  (isActive ? "bg-card font-medium" : "hover:bg-card/60")
                }
              >
                {project.name}
              </NavLink>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

// ---- 账户条（沿用原实现，加 i18n） ----------------------------------------

function AccountMenu() {
  const location = useLocation()
  const setSidebarOpen = useUi((state) => state.setSidebarOpen)
  const auth = useAuth()
  const { logout, busy: logoutBusy, error: logoutError } = useLogout()
  const { t } = useI18n()
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
    if (isMobileViewport()) setSidebarOpen(false)
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
                to="/settings/general"
                state={{ from: location.pathname + location.search }}
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
                onClick={closeOnMobile}
              >
                <IconSettings size={15} />
                {t("app.settings")}
              </NavLink>
              <button
                type="button"
                role="menuitem"
                disabled={logoutBusy}
                className={
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
                  "hover:bg-sidebar disabled:opacity-60"
                }
                onClick={logout}
              >
                <IconLogout size={15} />
                {logoutBusy ? "退出中…" : t("app.logout")}
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
                {t("app.login")}
              </NavLink>
              <NavLink
                to={isAppPath(next) ? `/register?next=${encodeURIComponent(next)}` : "/register"}
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-sidebar"
                onClick={closeOnMobile}
              >
                <IconPlus size={15} />
                {t("app.register")}
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
  const setSearchOpen = useUi((state) => state.setSearchOpen)
  const { t } = useI18n()
  const auth = useAuth()
  const [isMobile, setIsMobile] = useState(isMobileViewport)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
    enabled: auth.status === "authed",
  })
  const projects = projectsQuery.data ?? []

  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)")
    const sync = () => setIsMobile(query.matches)
    sync()
    query.addEventListener("change", sync)
    return () => query.removeEventListener("change", sync)
  }, [])

  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)")
    if (!open || !isMobile || !query.matches) return

    const previousOverflow = document.body.style.overflow
    const previousOverscroll = document.body.style.overscrollBehavior
    const active = document.activeElement
    returnFocusRef.current = active instanceof HTMLElement ? active : null
    document.body.style.overflow = "hidden"
    document.body.style.overscrollBehavior = "none"
    closeButtonRef.current?.focus({ preventScroll: true })

    return () => {
      document.body.style.overflow = previousOverflow
      document.body.style.overscrollBehavior = previousOverscroll
      const target = returnFocusRef.current
      returnFocusRef.current = null
      if (target?.isConnected) target.focus({ preventScroll: true })
    }
  }, [open, isMobile])

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
      {/* 桌面端收起 → 56px 图标轨（UI-2026-10-22 §01）；移动端收起 → 全隐藏。 */}
      {!open && !isMobile ? (
        <aside
          aria-label="快捷导航"
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-sidebar py-3"
        >
          <Link
            to="/app"
            aria-label={t("app.newTask")}
            title={t("app.newTask")}
            className="rounded-md p-2 text-muted hover:bg-card"
          >
            <IconPlus size={18} />
          </Link>
          <button
            type="button"
            aria-label={t("app.search")}
            title={t("app.search")}
            className="rounded-md p-2 text-muted hover:bg-card"
            onClick={() => setSearchOpen(true)}
          >
            <IconSearch size={18} />
          </button>
          <NavLink
            to="/scheduled"
            aria-label={t("app.scheduled")}
            title={t("app.scheduled")}
            className={({ isActive }) =>
              "rounded-md p-2 " + (isActive ? "bg-card text-foreground" : "text-muted hover:bg-card")
            }
          >
            <IconCalendar size={18} />
          </NavLink>
          <NavLink
            to="/settings/general"
            aria-label={t("app.settings")}
            title={t("app.settings")}
            className={({ isActive }) =>
              "mt-auto rounded-md p-2 " +
              (isActive ? "bg-card text-foreground" : "text-muted hover:bg-card")
            }
          >
            <IconSettings size={18} />
          </NavLink>
          <button
            type="button"
            aria-label="展开会话列表"
            title="展开会话列表"
            className="rounded-md p-2 text-muted hover:bg-card"
            onClick={() => setSidebarOpen(true)}
          >
            <IconMenu size={18} />
          </button>
        </aside>
      ) : null}
      <aside
        role={isMobile && open ? "dialog" : undefined}
        aria-label="会话列表"
        aria-hidden={!open}
        aria-modal={isMobile && open ? true : undefined}
        inert={!open}
        className={
          "rxy-sidebar-drawer fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r " +
          "border-border bg-sidebar transition-transform md:static " +
          (open ? "translate-x-0" : "-translate-x-full") +
          // 桌面端收起时由 56px 轨顶替 → 抽屉移出布局流。
          (open ? "" : " md:hidden")
        }
      >
        <div className="flex items-center justify-between px-3 py-3">
          <Link to="/app" className="px-1 text-sm font-semibold tracking-tight">
            RxyCode
          </Link>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="关闭会话列表"
            className="rounded-md p-1 text-muted hover:bg-card md:hidden"
            onClick={() => setSidebarOpen(false)}
          >
            <IconClose size={18} />
          </button>
        </div>
        <div className="space-y-1 px-2 pb-2">
          <Link
            to="/app"
            className={
              "flex items-center gap-2 rounded-md border border-border " +
              "bg-card px-3 py-2 text-sm font-medium hover:bg-background"
            }
          >
            <IconPlus size={16} />
            {t("app.newTask")}
          </Link>
          <button
            type="button"
            onClick={() => {
              setSearchOpen(true)
              if (isMobileViewport()) setSidebarOpen(false)
            }}
            className={
              "flex w-full items-center gap-2 rounded-md border border-border " +
              "px-3 py-2 text-sm text-muted hover:bg-card"
            }
          >
            <IconSearch size={15} />
            {t("app.search")}
            <kbd className="ml-auto rounded border border-border px-1 text-[10px]">Ctrl K</kbd>
          </button>
          <NavLink
            to="/scheduled"
            className={({ isActive }) =>
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm " +
              (isActive ? "bg-card font-medium" : "text-muted hover:bg-card/60")
            }
          >
            {t("app.scheduled")}
          </NavLink>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto">
          <ProjectSection />
          <SessionSections projects={projects} />
        </nav>
        <AccountMenu />
      </aside>
    </>
  )
}
