// 废弃（2026-10-20）：由 /app 控制台替代，保留到 W10 后删除
import { useMutation, useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { createClient } from "../../sdk/client"

function SessionControl({ projectId }: { projectId: string }) {
  const client = useMemo(() => createClient(), [])
  const [sessionId, setSessionId] = useState("")
  const create = useMutation({
    mutationFn: () => client.createSession(projectId, "首个任务"),
    onSuccess: (row) => setSessionId(row.id),
  })
  return (
    <div className="mt-3">
      <button
        type="button"
        className="rounded-md border border-border px-3 py-2 text-sm"
        onClick={() => create.mutate()}
      >
        创建会话
      </button>
      {sessionId ? (
        <p className="mt-2 text-sm" data-session-id={sessionId}>
          等待运行
        </p>
      ) : null}
    </div>
  )
}

export function ProjectPanel() {
  const client = useMemo(() => createClient(), [])
  const [name, setName] = useState("")
  const [keyValue, setKeyValue] = useState("")
  const [failed, setFailed] = useState(false)
  const list = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => client.listProjects(signal),
  })
  const create = useMutation({
    mutationFn: () => client.createProject(name.trim(), keyValue ? { secret: keyValue } : {}),
    onSuccess: async () => {
      setFailed(false)
      setName("")
      setKeyValue("")
      await list.refetch()
    },
    onError: () => setFailed(true),
  })
  return (
    <section className="mt-6">
      {list.isPending ? <p>正在加载</p> : null}
      {list.isError ? (
        <p role="alert">项目列表加载失败</p>
      ) : null}
      {list.isSuccess && list.data.length === 0 ? <p>还没有项目</p> : null}
      <form
        className="mt-4 grid gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          setFailed(false)
          create.mutate()
        }}
      >
        <label className="grid gap-1 text-sm">
          仓库名称
          <input
            className="rounded-md border border-border bg-card px-3 py-2"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm">
          密钥
          <input
            type="password"
            className="rounded-md border border-border bg-card px-3 py-2"
            value={keyValue}
            onChange={(event) => setKeyValue(event.target.value)}
          />
        </label>
        <button type="submit" className="rounded-md bg-foreground px-3 py-2 text-sm text-background">
          导入
        </button>
      </form>
      {failed ? <p role="alert">保存失败</p> : null}
      <div className="mt-4 grid gap-3">
        {list.data?.map((project) => (
          <article
            key={project.id}
            data-project-id={project.id}
            className="rounded-md border border-border bg-card p-3"
          >
            <h2 className="text-base font-semibold">{project.name}</h2>
            <SessionControl projectId={project.id} />
          </article>
        ))}
      </div>
    </section>
  )
}
