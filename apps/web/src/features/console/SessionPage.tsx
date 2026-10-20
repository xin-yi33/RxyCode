import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient, type RunSummary } from "../../sdk/client"
import { isUnauthorized } from "../../sdk/errors"
import { RunTimeline } from "../runs/RunTimeline"
import { isActiveRunStatus, runStatusKind, runStatusText } from "../runs/status"
import { Composer } from "./Composer"

const api = createClient()

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

function StatusChip({ status }: { status: string }) {
  return (
    <span
      data-run-status={status}
      className={
        "rounded-full px-2 py-0.5 text-xs " + chipClass[runStatusKind(status)]
      }
    >
      {runStatusText(status)}
    </span>
  )
}

function RunCard({ run }: { run: RunSummary }) {
  const live = isActiveRunStatus(run.status)
  return (
    <article className="space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-bubble px-4 py-2 text-sm leading-relaxed">
          {run.message}
        </p>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <StatusChip status={run.status} />
        {run.created_at ? (
          <time dateTime={run.created_at}>
            {new Date(run.created_at).toLocaleString()}
          </time>
        ) : null}
      </div>
      {live ? (
        <RunTimeline runId={run.run_id} live />
      ) : run.final_preview ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {run.final_preview}
        </p>
      ) : null}
    </article>
  )
}

export function SessionPage() {
  const { sessionId = "" } = useParams()
  const [older, setOlder] = useState<RunSummary[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>(undefined)
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

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 py-4">
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
          <li key={run.run_id}>
            <RunCard run={run} />
          </li>
        ))}
      </ol>
      <div className="sticky bottom-0 -mx-4 bg-background">
        <Composer sessionId={sessionId} />
      </div>
    </div>
  )
}
