import { useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"
import { apiErrorText } from "../../sdk/errors"
import { isActiveRunStatus } from "../runs/status"

const api = createClient()

// W9-F2: bottom steering console. Targets the current session's active run;
// F4 grows this into the full event console.
export function ConsolePanel() {
  const params = useParams()
  const sessionId = params.sessionId ?? ""
  const queryClient = useQueryClient()
  const [text, setText] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const runs = useQuery({
    queryKey: ["sessionRuns", sessionId],
    queryFn: ({ signal }) => api.listSessionRuns(sessionId, { limit: 5 }, signal),
    enabled: sessionId.length > 0,
    refetchInterval: 15_000,
  })
  const active = (runs.data?.runs ?? []).find((run) =>
    isActiveRunStatus(run.status),
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const message = text.trim()
    if (!active || busy || !message) return
    setBusy(true)
    setError("")
    api
      .steerRun(active.run_id, message)
      .then(() => {
        setText("")
        void queryClient.invalidateQueries({
          queryKey: ["sessionRuns", sessionId],
        })
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  const cancel = () => {
    if (!active || busy) return
    setBusy(true)
    api
      .cancelRun(active.run_id)
      .then(() => {
        void queryClient.invalidateQueries({
          queryKey: ["sessionRuns", sessionId],
        })
      })
      .catch((err: unknown) => setError(apiErrorText(err)))
      .finally(() => setBusy(false))
  }

  return (
    <section
      aria-label="控制台"
      className="shrink-0 border-t border-border bg-sidebar px-4 py-2"
    >
      <form onSubmit={submit} className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          aria-label="控制台输入"
          placeholder={
            active ? "向运行中的任务发送指令…" : "当前会话没有运行中的任务"
          }
          rows={1}
          className={
            "min-h-[38px] flex-1 resize-y rounded-md border border-border " +
            "bg-card px-3 py-2 text-sm outline-none focus:border-muted"
          }
          value={text}
          disabled={!active || busy}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={!active || busy || !text.trim()}>
          发送
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!active || busy}
          onClick={cancel}
        >
          取消运行
        </Button>
      </form>
      {error ? (
        <p role="alert" className="mx-auto mt-1 max-w-3xl text-xs text-failure">
          {error}
        </p>
      ) : null}
    </section>
  )
}
