import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, NavLink, useNavigate, useParams } from "react-router"

import { createClient, type SessionListItem } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { usePopover } from "../../lib/usePopover"
import { runStatusKind, runStatusText } from "../runs/status"

const api = createClient()

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

// 项目首页（02-SESSIONS §项目）：项目信息 + 作用域会话列表 + 项目菜单。
export function ProjectPage() {
  const { projectId = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [name, setName] = useState("")
  const [error, setError] = useState("")
  const popRef = usePopover<HTMLDivElement>(menuOpen, () => setMenuOpen(false))

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => api.getProject(projectId, signal),
  })
  const sessions = useQuery({
    queryKey: ["sessions", "project", projectId],
    queryFn: ({ signal }) => api.listSessions({ project_id: projectId, limit: 50 }, signal),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["project", projectId] })
    void queryClient.invalidateQueries({ queryKey: ["projects"] })
    void queryClient.invalidateQueries({ queryKey: ["sessions"] })
  }
  const fail = (err: unknown) => setError(apiErrorText(err))

  const rename = useMutation({
    mutationFn: () =>
      api.patchProject(projectId, {
        name: name.trim(),
        expected_revision: project.data?.project.revision,
      }),
    onSuccess: () => {
      setRenameOpen(false)
      invalidate()
    },
    onError: fail,
  })

  const remove = useMutation({
    mutationFn: () =>
      api.deleteProject(projectId, {
        expected_revision: project.data?.project.revision,
        keep_sessions: true,
      }),
    onSuccess: () => {
      invalidate()
      navigate("/app")
    },
    onError: fail,
  })

  if (project.isPending) {
    return <p className="px-6 py-8 text-sm text-muted">正在加载项目…</p>
  }
  if (project.isError) {
    return (
      <p role="alert" className="px-6 py-8 text-sm text-failure">
        {apiErrorText(project.error)}
      </p>
    )
  }
  const data = project.data.project

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {renameOpen ? (
            <div className="flex items-center gap-2">
              <input
                autoFocus
                defaultValue={data.name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && name.trim()) rename.mutate()
                  if (e.key === "Escape") setRenameOpen(false)
                }}
                className="rounded-md border border-border bg-background px-2 py-1 text-lg font-semibold"
                aria-label="项目名称"
              />
              <button
                type="button"
                className="text-sm"
                disabled={rename.isPending}
                onClick={() => rename.mutate()}
              >
                保存
              </button>
            </div>
          ) : (
            <h2 className="truncate text-lg font-semibold">{data.name}</h2>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="rounded-full bg-border px-2 py-0.5">
              {data.memory_mode === "project_only" ? "仅项目记忆" : "默认记忆"}
            </span>
            {data.is_default ? (
              <span className="rounded-full bg-border px-2 py-0.5">默认项目</span>
            ) : null}
            {data.pinned ? <span className="rounded-full bg-border px-2 py-0.5">已置顶</span> : null}
          </div>
        </div>
        <div className="relative" ref={popRef}>
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="项目操作"
            className="rounded-md border border-border px-2 py-1 text-sm hover:bg-card"
            onClick={() => setMenuOpen((v) => !v)}
          >
            ⋯
          </button>
          {menuOpen ? (
            <div
              role="menu"
              className="absolute right-0 top-full z-40 mt-1 w-48 overflow-hidden rounded-lg border border-border bg-card shadow-md"
            >
              <button
                type="button"
                role="menuitem"
                className="block w-full px-3 py-2 text-left text-sm hover:bg-sidebar"
                onClick={() => {
                  setName(data.name)
                  setRenameOpen(true)
                  setMenuOpen(false)
                }}
              >
                重命名
              </button>
              <Link
                to={`/projects/${projectId}/memory`}
                role="menuitem"
                className="block px-3 py-2 text-sm hover:bg-sidebar"
                onClick={() => setMenuOpen(false)}
              >
                项目记忆
              </Link>
              {!data.is_default ? (
                <button
                  type="button"
                  role="menuitem"
                  className="block w-full px-3 py-2 text-left text-sm text-failure hover:bg-sidebar"
                  onClick={() => {
                    setConfirmDelete(true)
                    setMenuOpen(false)
                  }}
                >
                  删除项目
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {confirmDelete ? (
        <div role="alertdialog" className="mt-3 rounded-lg border border-failure/40 bg-card p-3">
          <p className="text-sm">删除项目「{data.name}」？会话将移入默认项目。</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="text-sm text-failure"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? "删除中…" : "确认删除"}
            </button>
            <button type="button" className="text-sm text-muted" onClick={() => setConfirmDelete(false)}>
              取消
            </button>
          </div>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-failure">
          {error}
        </p>
      ) : null}

      <h3 className="mt-8 text-sm font-medium text-muted">会话</h3>
      {sessions.isPending ? (
        <p className="mt-2 text-sm text-muted">正在加载会话…</p>
      ) : sessions.isError ? (
        <p role="alert" className="mt-2 text-sm text-failure">
          {apiErrorText(sessions.error)}
        </p>
      ) : (sessions.data?.sessions ?? []).length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          还没有会话。<Link className="underline" to="/app">新建任务</Link>
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {(sessions.data?.sessions ?? []).map((session: SessionListItem) => {
            const status = session.last_run?.status ?? ""
            return (
              <li key={session.id}>
                <NavLink
                  to={`/app/s/${session.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-4 py-2.5 text-sm hover:bg-background"
                >
                  <span className="min-w-0 truncate">
                    {session.title || "未命名会话"}
                    {session.archived ? (
                      <span className="ml-1 text-xs text-muted">（已归档）</span>
                    ) : null}
                  </span>
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
                </NavLink>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
