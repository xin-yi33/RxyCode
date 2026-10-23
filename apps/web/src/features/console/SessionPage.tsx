import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router"

import { Button } from "../../components/ui/button"
import {
  createClient,
  type ArtifactItem,
  type PreviewJob,
  type RunSummary,
} from "../../sdk/client"
import { isUnauthorized } from "../../sdk/errors"
import { PreviewDrawer } from "../preview/PreviewDrawer"
import { ArtifactRows } from "../runs/ArtifactRows"
import { RunTimeline } from "../runs/RunTimeline"
import { isActiveRunStatus } from "../runs/status"
import { Composer } from "./Composer"
import { SessionFiles } from "./SessionFiles"

const api = createClient()

function RunCard({
  run,
  onPreview,
}: {
  run: RunSummary
  onPreview: (artifact: ArtifactItem) => void
}) {
  // W9-F4: 用户消息气泡、状态行、工具/审批/问题/Final 全部由 RunTimeline
  // 渲染 —— 这里不再画重复的状态行。模型行回显提交时的解析快照
  // （FR-17）；历史 run 没有记录就如实标注，不用当前选择补写过去。
  const model = run.model
  return (
    <article className="space-y-3">
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>
          模型：
          {model ? (model.display_name || model.model_id) : "未记录（历史任务）"}
        </span>
        {model?.provider_name ? <span>· {model.provider_name}</span> : null}
        {model ? (
          <span className="rounded-full bg-border px-1.5 py-0.5 text-muted-ink">
            {model.credential_source === "platform" ? "平台" : "个人"}
          </span>
        ) : null}
      </p>
      <RunTimeline run={run} />
      <ArtifactRows runId={run.run_id} status={run.status} onPreview={onPreview} />
    </article>
  )
}

export function SessionPage() {
  const { sessionId = "" } = useParams()
  const [older, setOlder] = useState<RunSummary[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>(undefined)
  const [preview, setPreview] = useState<{ title: string; job: PreviewJob | null } | null>(null)
  const previewPoll = useQuery({
    queryKey: ["preview-job", preview?.job?.preview_id],
    enabled: Boolean(
      preview?.job &&
        (preview.job.status === "queued" || preview.job.status === "running"),
    ),
    queryFn: ({ signal }) => api.getPreview(preview!.job!.preview_id, signal),
    refetchInterval: 1_000,
  })
  const liveJob = (previewPoll.data as PreviewJob | undefined) ?? preview?.job ?? null
  const openPreview = (artifact: ArtifactItem) => {
    const title = artifact.filename || artifact.relative_path
    setPreview({ title, job: null })
    void api
      .createPreview(artifact.artifact_id)
      .then((job) => setPreview({ title, job }))
      .catch(() => setPreview(null))
  }
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: ({ signal }) => api.getSession(sessionId, signal),
  })
  const runs = useQuery({
    queryKey: ["sessionRuns", sessionId],
    queryFn: ({ signal }) => api.listSessionRuns(sessionId, { limit: 20 }, signal),
    refetchInterval: (query) => {
      const items = query.state.data?.runs ?? []
      return items.some((run) => isActiveRunStatus(run.status)) ? 5_000 : false
    },
  })

  const nextCursor = cursor === undefined ? runs.data?.next_cursor ?? null : cursor
  const loadEarlier = () => {
    if (!nextCursor) return
    void api
      .listSessionRuns(sessionId, { limit: 20, before: nextCursor })
      .then((page) => {
        setOlder((current) => [...current, ...page.runs])
        setCursor(page.next_cursor)
      })
  }

  if (session.isError && !isUnauthorized(session.error)) {
    return (
      <div role="alert" className="p-6 text-sm text-muted">
        无法连接服务器{" "}
        <button type="button" className="underline" onClick={() => void session.refetch()}>
          重试
        </button>
      </div>
    )
  }

  // Backend returns newest-first; render oldest-first like a chat log.
  const ordered = [...older, ...(runs.data?.runs ?? [])].reverse()
  const active = ordered.find((run) => isActiveRunStatus(run.status)) ?? null

  const archived = session.data?.archived === true || Boolean(session.data?.archived_at)

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 py-4">
      {archived ? (
        <div
          role="status"
          className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-waiting/40 bg-waiting/10 px-3 py-2 text-sm text-waiting-ink"
        >
          <span>此会话已归档，内容只读。取消归档后可继续对话。</span>
          <button
            type="button"
            className="shrink-0 underline"
            onClick={() => {
              void api
                .unarchiveSession(sessionId, {
                  expected_revision: session.data?.revision,
                })
                .then(() => void session.refetch())
            }}
          >
            取消归档
          </button>
        </div>
      ) : null}
      {runs.isPending ? (
        <p className="py-8 text-center text-sm text-muted">正在加载任务…</p>
      ) : null}
      {ordered.length === 0 && runs.isSuccess ? (
        <p className="py-8 text-center text-sm text-muted">
          这个会话还没有任务，从下方输入框开始。
        </p>
      ) : null}
      {nextCursor ? (
        <div className="pb-2 text-center">
          <Button variant="outline" size="sm" onClick={loadEarlier}>
            加载更早的任务
          </Button>
        </div>
      ) : null}
      <ol className="flex-1 space-y-8 pb-6">
        {ordered.map((run) => (
          <li key={run.run_id} id={`run-${run.run_id}`}>
            <RunCard run={run} onPreview={openPreview} />
          </li>
        ))}
      </ol>
      <PreviewDrawer
        job={liveJob}
        title={preview?.title ?? ""}
        open={preview !== null}
        onClose={() => setPreview(null)}
      />
      <div className="sticky bottom-0 -mx-4 space-y-2 bg-background">
        {archived ? null : (
          <>
            <SessionFiles sessionId={sessionId} hasActive={active !== null} />
            <Composer sessionId={sessionId} activeRun={active} />
          </>
        )}
      </div>
    </div>
  )
}
