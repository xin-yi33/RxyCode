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
import { usePatchPreferences, usePreferences } from "../../state/prefs"
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

// ---- 会话条目菜单：重命名/置顶/分享/移动/归档/删除（SES-02..09） -----------

const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "pending",
  "running",
  "waiting_approval",
  "waiting",
])

function sessionBusy(session: SessionListItem): boolean {
  return ACTIVE_RUN_STATUSES.has(session.last_run?.status ?? "")
}

// SES-07 强确认：居中 modal，只有取消/删除两个出口；外部点击与 Escape
// 一律不关闭（无 onClick 背景关闭、无 Escape 监听）。
function DeleteChatModal({
  session,
  error,
  busy,
  onCancel,
  onDelete,
}: {
  session: SessionListItem
  error: string
  busy: boolean
  onCancel: () => void
  onDelete: () => void
}) {
  const { t } = useI18n()
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-chat-title"
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
      >
        <h2 id="delete-chat-title" className="text-base font-semibold">
          {t("session.deleteChatTitle")}
        </h2>
        <p className="mt-1 truncate text-sm font-medium">{session.title || "未命名会话"}</p>
        <p className="mt-2 text-sm text-muted">{t("session.deleteForever")}</p>
        {error ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={onCancel}
          >
            {t("app.cancel")}
          </button>
          <button
            type="button"
            className="rounded-md bg-failure px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            disabled={busy}
            onClick={onDelete}
          >
            {t("session.delete")}
          </button>
        </div>
      </div>
    </div>
  )
}

type OrderControls = {
  canUp: boolean
  canDown: boolean
  onMove: (dir: -1 | 1) => void
}

function SessionMenu({
  session,
  projects,
  order,
  onClose,
}: {
  session: SessionListItem
  projects: Project[]
  order?: OrderControls
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { t } = useI18n()
  const showToast = useUi((state) => state.showToast)
  const [error, setError] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [projectQuery, setProjectQuery] = useState("")
  const [pendingMove, setPendingMove] = useState<Project | "out" | null>(null)
  const [title, setTitle] = useState(session.title)
  const popRef = usePopover<HTMLDivElement>(!confirmDelete, onClose)
  const runBusy = sessionBusy(session)

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

  const share = async () => {
    // SES-05：复制目标会话的 canonical URL（不是当前页面地址）。
    const url = `${window.location.origin}/app/s/${session.id}`
    try {
      await navigator.clipboard.writeText(url)
      showToast(t("session.linkCopied"))
      onClose()
    } catch {
      setError(t("session.copyFail"))
    }
  }

  const moveTargets = projects.filter((p) => !p.is_default)
  const defaultProject = projects.find((p) => p.is_default)
  const filteredTargets = projectQuery.trim()
    ? moveTargets.filter((p) =>
        p.name.toLowerCase().includes(projectQuery.trim().toLowerCase()),
      )
    : moveTargets
  const inNamedProject =
    !defaultProject || session.project_id !== defaultProject.id

  const item = (
    label: string,
    onClick: () => void,
    opts: { danger?: boolean; disabled?: boolean; title?: string } = {},
  ) => (
    <button
      type="button"
      role="menuitem"
      disabled={busy || opts.disabled}
      title={opts.title}
      onClick={onClick}
      className={
        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
        "hover:bg-sidebar disabled:opacity-60 " +
        (opts.danger ? "text-failure" : "")
      }
    >
      {label}
    </button>
  )

  return (
    <>
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
          <div className="flex max-h-64 flex-col">
            {pendingMove !== null ? (
              // SES-08 记忆边界确认 —— 选定目标后二次确认，不直接执行。
              <div className="p-3">
                <p className="text-xs text-muted">{t("session.memoryWarn")}</p>
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    type="button"
                    className="text-xs text-muted"
                    onClick={() => setPendingMove(null)}
                  >
                    {t("app.cancel")}
                  </button>
                  <button
                    type="button"
                    className="text-xs font-medium"
                    disabled={busy}
                    onClick={() =>
                      move.mutate(
                        pendingMove === "out"
                          ? "none"
                          : (pendingMove as Project).id,
                      )
                    }
                  >
                    {t("session.move")}
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="border-b border-border p-2">
                  <input
                    autoFocus
                    value={projectQuery}
                    onChange={(e) => setProjectQuery(e.target.value)}
                    placeholder={t("session.searchProjects")}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                    aria-label={t("session.searchProjects")}
                  />
                </div>
                <div className="flex-1 overflow-y-auto py-1">
                  {inNamedProject && defaultProject ? (
                    <button
                      type="button"
                      role="menuitem"
                      disabled={busy}
                      onClick={() => setPendingMove("out")}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-sidebar disabled:opacity-50"
                    >
                      {t("session.moveOut")}
                    </button>
                  ) : null}
                  {filteredTargets.map((project) => (
                    <button
                      key={project.id}
                      type="button"
                      role="menuitem"
                      disabled={busy || project.id === session.project_id}
                      onClick={() => setPendingMove(project)}
                      className={
                        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm " +
                        "hover:bg-sidebar disabled:opacity-50"
                      }
                    >
                      <span className="truncate">{project.name}</span>
                      {project.id === session.project_id ? " ✓" : ""}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            {item(t("session.rename"), () => setRenameOpen(true))}
            {item(session.pinned ? t("session.unpin") : t("session.pin"), () => togglePin.mutate())}
            {order
              ? item(t("sidebar.moveUp"), () => order.onMove(-1), { disabled: !order.canUp })
              : null}
            {order
              ? item(t("sidebar.moveDown"), () => order.onMove(1), { disabled: !order.canDown })
              : null}
            {item(t("session.share"), () => void share())}
            {item(t("session.moveTo"), () => setMoveOpen(true), {
              disabled: runBusy,
              title: runBusy ? t("session.busyBlocked") : undefined,
            })}
            {item(
              session.archived ? t("session.unarchive") : t("session.archive"),
              () => toggleArchive.mutate(),
              {
                disabled: !session.archived && runBusy,
                title: !session.archived && runBusy ? t("session.busyBlocked") : undefined,
              },
            )}
            {item(t("session.delete"), () => setConfirmDelete(true), {
              danger: true,
              disabled: runBusy,
              title: runBusy ? t("session.busyBlocked") : undefined,
            })}
          </>
        )}
        {error ? (
          <p role="alert" className="px-3 py-2 text-xs text-failure">
            {error}
          </p>
        ) : null}
      </div>
      {confirmDelete ? (
        <DeleteChatModal
          session={session}
          error={error}
          busy={busy}
          onCancel={() => setConfirmDelete(false)}
          onDelete={() => del.mutate()}
        />
      ) : null}
    </>
  )
}

function SessionRow({
  session,
  projects,
  projectTag = "",
  order,
}: {
  session: SessionListItem
  projects: Project[]
  projectTag?: string
  order?: OrderControls
}) {
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
          <span className="min-w-0 truncate">
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
        {/* PROJ-04 合并显示：最近行带项目副标。 */}
        {projectTag ? (
          <span className="mt-0.5 block truncate text-xs text-muted">
            {projectTag}
          </span>
        ) : null}
      </NavLink>
      <button
        type="button"
        aria-label="会话操作"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
        className={
          "absolute right-1 top-2 rounded px-1.5 py-0.5 " +
          "text-muted opacity-0 hover:bg-sidebar focus:opacity-100 " +
          "group-hover:opacity-100 " +
          (menuOpen ? "opacity-100" : "")
        }
      >
        ⋯
      </button>
      {menuOpen ? (
        <SessionMenu
          session={session}
          projects={projects}
          order={order}
          onClose={() => setMenuOpen(false)}
        />
      ) : null}
    </li>
  )
}

// ---- 分区偏好（§02 PROJ-02/REC-02）：grouping/sort/show_projects/折叠 ----

type SidebarPrefs = {
  grouping: "project" | "merged"
  sort: "updated_at" | "manual"
  show_projects: boolean
  projects_collapsed: boolean
  recent_collapsed: boolean
}

const DEFAULT_SIDEBAR_PREFS: SidebarPrefs = {
  grouping: "merged",
  sort: "updated_at",
  show_projects: true,
  projects_collapsed: false,
  recent_collapsed: false,
}

function useSidebarPrefs(): [SidebarPrefs, (patch: Partial<SidebarPrefs>) => void] {
  const prefs = usePreferences()
  const patch = usePatchPreferences()
  const sb = { ...DEFAULT_SIDEBAR_PREFS, ...(prefs.data?.sidebar ?? {}) }
  return [
    sb,
    (partial) =>
      patch.mutate({ sidebar: partial, expected_revision: prefs.data?.revision }),
  ]
}

/** 分区 ⋯ 菜单：整理侧边栏（分组/排序）+ 显示项目区（REC-02）。 */
function SidebarPrefsMenu({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const [sb, setSb] = useSidebarPrefs()
  const popRef = usePopover<HTMLDivElement>(true, onClose)
  const row = (
    label: string,
    checked: boolean,
    onClick: () => void,
    role: "menuitemradio" | "menuitemcheckbox" = "menuitemradio",
  ) => (
    <button
      type="button"
      role={role}
      aria-checked={checked}
      onClick={onClick}
      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-sidebar"
    >
      {label}
      {checked ? <span aria-hidden>✓</span> : null}
    </button>
  )
  return (
    <div
      ref={popRef}
      role="menu"
      className="absolute right-0 top-full z-50 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-md"
    >
      <p className="px-3 pb-1 pt-1 text-xs font-medium text-muted">
        {t("sidebar.grouping")}
      </p>
      {row(t("sidebar.groupProject"), sb.grouping === "project", () =>
        setSb({ grouping: "project" }),
      )}
      {row(t("sidebar.groupMerged"), sb.grouping === "merged", () =>
        setSb({ grouping: "merged" }),
      )}
      <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted">
        {t("sidebar.sortBy")}
      </p>
      {row(t("sidebar.sortUpdated"), sb.sort === "updated_at", () =>
        setSb({ sort: "updated_at" }),
      )}
      {row(t("sidebar.sortManual"), sb.sort === "manual", () =>
        setSb({ sort: "manual" }),
      )}
      <div className="my-1 border-t border-border" />
      {row(
        t("sidebar.showProjects"),
        sb.show_projects,
        () => setSb({ show_projects: !sb.show_projects }),
        "menuitemcheckbox",
      )}
    </div>
  )
}

function SectionHeader({
  title,
  collapsed,
  onToggle,
  onPlus,
  plusLabel,
}: {
  title: string
  collapsed: boolean
  onToggle: () => void
  onPlus?: () => void
  plusLabel?: string
}) {
  const { t } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)
  return (
    <div className="group/header relative flex items-center justify-between px-4 pb-1 pt-3">
      <button
        type="button"
        aria-expanded={!collapsed}
        title={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
        className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted hover:text-foreground"
        onClick={onToggle}
      >
        <span aria-hidden className="inline-block w-3 text-[10px]">
          {collapsed ? "▸" : "▾"}
        </span>
        {title}
      </button>
      <span className="relative flex items-center gap-0.5">
        <button
          type="button"
          aria-label={t("sidebar.organize")}
          aria-haspopup="menu"
          className={
            "rounded p-0.5 text-muted hover:bg-card focus:opacity-100 " +
            "opacity-0 group-hover/header:opacity-100 " +
            (menuOpen ? "opacity-100" : "")
          }
          onClick={() => setMenuOpen((v) => !v)}
        >
          ⋯
        </button>
        {onPlus ? (
          <button
            type="button"
            aria-label={plusLabel}
            title={plusLabel}
            className="rounded p-0.5 text-muted hover:bg-card"
            onClick={onPlus}
          >
            <IconPlus size={14} />
          </button>
        ) : null}
        {menuOpen ? <SidebarPrefsMenu onClose={() => setMenuOpen(false)} /> : null}
      </span>
    </div>
  )
}

/** 手动排序（PROJ-06）：上移/下移当前可见列表，走 API-ORDER 持久化。 */
function useListReorder(
  scope: "pinned_sessions" | "projects" | "project_sessions" | "recent",
  ids: string[],
  projectId?: string,
) {
  const queryClient = useQueryClient()
  const reorder = useMutation({
    mutationFn: (orderedIds: string[]) =>
      api.putSidebarOrder({
        scope,
        project_id: projectId,
        ordered_ids: orderedIds,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
    },
  })
  return (id: string, dir: -1 | 1) => {
    const index = ids.indexOf(id)
    const next = index + dir
    if (index < 0 || next < 0 || next >= ids.length) return
    const copy = ids.slice()
    ;[copy[index], copy[next]] = [copy[next], copy[index]]
    reorder.mutate(copy)
  }
}

// ---- 创建项目 modal（PROJ-07..09）：名称 + 记忆模式 ----------------------

function CreateProjectModal({
  busy,
  error,
  onCancel,
  onCreate,
}: {
  busy: boolean
  error: string
  onCancel: () => void
  onCreate: (name: string, memoryMode: string) => void
}) {
  const { t } = useI18n()
  const [name, setName] = useState("")
  const [memoryMode, setMemoryMode] = useState("default")
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])
  // Esc 挂 document：点过遮罩后焦点回落到 body，弹层内的 onKeyDown
  // 不再收到事件 —— 显式 Esc 出口必须在任何焦点位置都可用。必须
  // stopPropagation：window 层监听（ConsolePanel/SplitWorkspace）只豁免
  // 原生 dialog[open]，本 div 弹层不拦截会把同一 Esc 传到下层面板。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        onCancel()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onCancel])
  const submit = () => {
    if (name.trim()) onCreate(name.trim(), memoryMode)
  }
  // 表单弹层 maskClosable=false：遮罩点击不关闭（误点不丢项目名/记忆设置），
  // 关闭走右上 ✕ / 「取消」/ Esc。
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-project-title"
        className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-lg"
      >
        <div className="flex items-start justify-between">
          <h2 id="create-project-title" className="text-base font-semibold">
            {t("project.createTitle")}
          </h2>
          <button
            type="button"
            aria-label={t("app.close")}
            className="rounded p-1 text-muted hover:bg-sidebar"
            onClick={onCancel}
          >
            <IconClose size={16} />
          </button>
        </div>
        <input
          autoFocus
          value={name}
          placeholder={t("project.namePlaceholder")}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit()
          }}
          className="mt-3 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          aria-label={t("project.namePlaceholder")}
        />
        <p className="mt-3 text-sm text-muted">{t("project.purpose")}</p>
        <div className="mt-4">
          <label className="mb-1 block text-xs font-medium text-muted">
            {t("sidebar.grouping")} · {t("project.memoryDefault")}
          </label>
          <select
            value={memoryMode}
            onChange={(e) => setMemoryMode(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-2 text-sm"
            aria-label="memory mode"
          >
            <option value="default">
              {t("project.memoryDefault")} — {t("project.memoryDefaultHint")}
            </option>
            <option value="project_only">
              {t("project.memoryOnly")} — {t("project.memoryOnlyHint")}
            </option>
          </select>
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-xs text-failure">
            {error}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={onCancel}
          >
            {t("app.cancel")}
          </button>
          <button
            type="button"
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink disabled:opacity-60"
            disabled={!name.trim() || busy}
            onClick={submit}
          >
            {t("project.create")}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- 项目行 ⋯ 菜单（图20）：置顶/上移/下移/重命名/设置/删除 ----------------

function ProjectMenu({
  project,
  canUp,
  canDown,
  onMove,
  onDelete,
  onClose,
}: {
  project: Project
  canUp: boolean
  canDown: boolean
  onMove: (dir: -1 | 1) => void
  onDelete: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState("")
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(project.name)
  const popRef = usePopover<HTMLDivElement>(true, onClose)

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patchProject(project.id, {
        ...body,
        expected_revision: project.revision,
      } as Parameters<typeof api.patchProject>[1]),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
      onClose()
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  const row = (label: string, onClick: () => void, disabled = false) => (
    <button
      type="button"
      role="menuitem"
      disabled={disabled || patch.isPending}
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-sidebar disabled:opacity-60"
    >
      {label}
    </button>
  )

  return (
    <div
      ref={popRef}
      role="menu"
      className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-md"
    >
      {renaming ? (
        <div className="p-2">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) patch.mutate({ name: name.trim() })
              if (e.key === "Escape") setRenaming(false)
            }}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            aria-label={t("project.rename")}
          />
        </div>
      ) : (
        <>
          {row(project.pinned ? t("session.unpin") : t("session.pin"), () =>
            patch.mutate({ pinned: !project.pinned }),
          )}
          {row(t("sidebar.moveUp"), () => onMove(-1), !canUp)}
          {row(t("sidebar.moveDown"), () => onMove(1), !canDown)}
          {row(t("project.rename"), () => setRenaming(true))}
          {row(t("project.settings"), () => {
            navigate(`/app/p/${project.id}`)
            onClose()
          })}
          {row(t("project.delete"), onDelete)}
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

// ---- 会话列表（pinned / recent / project-grouped） -----------------------

function SessionList({
  sessions,
  projects,
  manualScope,
  projectId,
  showProjectTag,
}: {
  sessions: SessionListItem[]
  projects: Project[]
  manualScope?: "pinned_sessions" | "project_sessions" | "recent"
  projectId?: string
  showProjectTag?: boolean
}) {
  const [sb] = useSidebarPrefs()
  const projectName = (id: string) =>
    projects.find((p) => p.id === id)?.name ?? ""
  const reorder = useListReorder(
    manualScope ?? "recent",
    sessions.map((s) => s.id),
    projectId,
  )
  return (
    <ul className="space-y-1 px-2">
      {sessions.map((session, index) => (
        <SessionRow
          key={session.id}
          session={session}
          projects={projects}
          projectTag={showProjectTag ? projectName(session.project_id) : ""}
          order={
            sb.sort === "manual" && manualScope
              ? {
                  canUp: index > 0,
                  canDown: index < sessions.length - 1,
                  onMove: (dir: -1 | 1) => reorder(session.id, dir),
                }
              : undefined
          }
        />
      ))}
    </ul>
  )
}

function SessionSections({
  projects,
  sessions,
}: {
  projects: Project[]
  sessions: SessionListItem[]
}) {
  const { t } = useI18n()
  const [sb, setSb] = useSidebarPrefs()
  const defaultIds = new Set(
    projects.filter((p) => p.is_default).map((p) => p.id),
  )
  const pinned = sessions
    .filter((s) => s.pinned)
    .sort((a, b) => (a.pin_order ?? 0) - (b.pin_order ?? 0))
  const unpinned = sessions.filter((s) => !s.pinned)
  // PROJ-03：按项目分组时，归属命名项目的聊天进项目树，不再重复进最近区。
  const namedProjectIds = new Set(
    projects.filter((p) => !p.is_default).map((p) => p.id),
  )
  const inNamedProject = (s: SessionListItem) =>
    !defaultIds.has(s.project_id) && namedProjectIds.has(s.project_id)
  const recent =
    sb.grouping === "project"
      ? unpinned.filter((s) => !inNamedProject(s))
      : unpinned

  return (
    <div className="pb-4">
      {pinned.length ? (
        <>
          <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted">
            {t("app.pinned")}
          </p>
          <SessionList
            sessions={pinned}
            projects={projects}
            manualScope="pinned_sessions"
          />
        </>
      ) : null}
      <SectionHeader
        title={t("app.recent")}
        collapsed={sb.recent_collapsed}
        onToggle={() => setSb({ recent_collapsed: !sb.recent_collapsed })}
      />
      {sb.recent_collapsed ? null : recent.length ? (
        <SessionList
          sessions={recent}
          projects={projects}
          manualScope="recent"
          showProjectTag={sb.grouping === "merged"}
        />
      ) : (
        <p className="px-3 py-2 text-sm text-muted">{t("app.noSessions")}</p>
      )}
    </div>
  )
}

// ---- 项目区（PROJ-01..09）：折叠/⋯菜单/创建modal/行内聊天 -----------------

function ProjectRow({
  project,
  sessions,
  projects,
  canUp,
  canDown,
  onMove,
}: {
  project: Project
  sessions: SessionListItem[]
  projects: Project[]
  canUp: boolean
  canDown: boolean
  onMove: (dir: -1 | 1) => void
}) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [menuOpen, setMenuOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState("")
  const del = useMutation({
    mutationFn: () =>
      api.deleteProject(project.id, { expected_revision: project.revision }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
      setConfirmDelete(false)
    },
    onError: (err) => setError(apiErrorText(err)),
  })
  return (
    <li className="group relative">
      <div className="flex items-center">
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={`${project.name} ${t("project.chats")}`}
          className="w-5 shrink-0 px-1 text-[10px] text-muted hover:text-foreground"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <NavLink
          to={`/app/p/${project.id}`}
          className={({ isActive }) =>
            "block min-w-0 flex-1 truncate rounded-md px-1 py-1.5 pr-8 text-sm " +
            (isActive ? "bg-card font-medium" : "hover:bg-card/60")
          }
        >
          {project.name}
          {project.memory_mode === "project_only" ? (
            <span className="ml-1 text-[10px] text-muted">🔒</span>
          ) : null}
        </NavLink>
        <button
          type="button"
          aria-label={`${project.name} ⋯`}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((v) => !v)}
          className={
            "absolute right-1 rounded px-1.5 py-0.5 text-muted " +
            "opacity-0 hover:bg-sidebar focus:opacity-100 " +
            "group-hover:opacity-100 " +
            (menuOpen ? "opacity-100" : "")
          }
        >
          ⋯
        </button>
        {menuOpen ? (
          <ProjectMenu
            project={project}
            canUp={canUp}
            canDown={canDown}
            onMove={onMove}
            onDelete={() => {
              setMenuOpen(false)
              setConfirmDelete(true)
            }}
            onClose={() => setMenuOpen(false)}
          />
        ) : null}
      </div>
      {expanded ? (
        <div className="ml-5 border-l border-border pl-2">
          {/* PROJ-03：项目树内行内新聊天入口 → 项目首页 composer。 */}
          <button
            type="button"
            className="block w-full rounded-md px-3 py-1.5 text-left text-sm text-muted hover:bg-card/60"
            onClick={() => navigate(`/app/p/${project.id}`)}
          >
            + {t("sidebar.newChatHere")}
          </button>
          {sessions.length ? (
            <SessionList
              sessions={sessions}
              projects={projects}
              manualScope="project_sessions"
              projectId={project.id}
            />
          ) : null}
        </div>
      ) : null}
      {confirmDelete ? (
        <div
          role="presentation"
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
        >
          <div
            role="alertdialog"
            aria-modal="true"
            className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
          >
            <h2 className="text-base font-semibold">{t("project.deleteTitle")}</h2>
            <p className="mt-1 truncate text-sm font-medium">{project.name}</p>
            <p className="mt-2 text-sm text-muted">{t("project.deleteConfirm")}</p>
            {error ? (
              <p role="alert" className="mt-2 text-xs text-failure">
                {error}
              </p>
            ) : null}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-sm"
                onClick={() => setConfirmDelete(false)}
              >
                {t("app.cancel")}
              </button>
              <button
                type="button"
                className="rounded-md bg-failure px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
                disabled={del.isPending}
                onClick={() => del.mutate()}
              >
                {t("app.delete")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </li>
  )
}

function ProjectSection({ sessions }: { sessions: SessionListItem[] }) {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState("")
  const [sb, setSb] = useSidebarPrefs()
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
    enabled: auth.status === "authed",
  })
  const create = useMutation({
    mutationFn: (input: { name: string; memoryMode: string }) =>
      api.createProjectEx({
        name: input.name,
        memory_mode: input.memoryMode,
        request_id: crypto.randomUUID(),
      }),
    onSuccess: () => {
      setCreating(false)
      void queryClient.invalidateQueries({ queryKey: ["projects"] })
    },
    onError: (err) => setError(apiErrorText(err)),
  })

  if (auth.status !== "authed") return null
  const projects = (query.data ?? []).filter((p) => !p.is_default)
  const reorder = useListReorder("projects", projects.map((p) => p.id))
  const projectSessions = (pid: string) =>
    sessions.filter((s) => !s.pinned && s.project_id === pid)
  return (
    <div className="pb-2">
      <SectionHeader
        title={t("app.projects")}
        collapsed={sb.projects_collapsed}
        onToggle={() => setSb({ projects_collapsed: !sb.projects_collapsed })}
        onPlus={() => setCreating(true)}
        plusLabel={t("project.create")}
      />
      {sb.projects_collapsed ? null : projects.length ? (
        <ul className="space-y-1 px-2">
          {projects.map((project, index) => (
            <ProjectRow
              key={project.id}
              project={project}
              projects={projects}
              sessions={sb.grouping === "project" ? projectSessions(project.id) : []}
              canUp={index > 0}
              canDown={index < projects.length - 1}
              onMove={(dir) => reorder(project.id, dir)}
            />
          ))}
        </ul>
      ) : null}
      {creating ? (
        <CreateProjectModal
          busy={create.isPending}
          error={error}
          onCancel={() => {
            setCreating(false)
            setError("")
          }}
          onCreate={(name, memoryMode) => create.mutate({ name, memoryMode })}
        />
      ) : null}
    </div>
  )
}

// ---- 会话数据装载（pinned/projects/recent 共用同一份列表） -----------------

function ConsoleLists() {
  const location = useLocation()
  const auth = useAuth()
  const [sb] = useSidebarPrefs()
  const query = useQuery({
    queryKey: ["sessions", "sidebar", sb.sort],
    queryFn: ({ signal }) =>
      api.listSessions(
        { archived: "false", limit: 50, sort: sb.sort === "manual" ? "manual" : "updated_at" },
        signal,
      ),
    refetchInterval: 15_000,
    enabled: auth.status === "authed",
  })
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.listProjects(signal),
    enabled: auth.status === "authed",
  })
  const projects = projectsQuery.data ?? []
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
  return (
    <>
      {sb.show_projects ? <ProjectSection sessions={query.data?.sessions ?? []} /> : null}
      <SessionSections
        projects={projects}
        sessions={query.data?.sessions ?? []}
      />
    </>
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
                to="/settings/general-settings"
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
  const [isMobile, setIsMobile] = useState(isMobileViewport)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

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
            to="/settings/general-settings"
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
        <nav className="min-h-24 flex-1 overflow-y-auto">
          <ConsoleLists />
        </nav>
        <AccountMenu />
      </aside>
    </>
  )
}
