import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useParams } from "react-router"

export type ScheduleJob = {
  id: string
  enabled: boolean
  notify: boolean
}

export type StatusNotice = {
  id: string
  status: string
  run_id: string
}

export function scheduleMarkup(job: ScheduleJob): string {
  const enabled = job.enabled ? "true" : "false"
  const notify = job.notify ? "true" : "false"
  return `<section data-schedule data-id="${job.id}" data-enabled="${enabled}" data-notify="${notify}"></section>`
}

async function csrfToken(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" })
  const payload = (await response.json()) as { csrf_token?: string }
  return payload.csrf_token ?? ""
}

async function loadNotices(): Promise<StatusNotice[]> {
  const response = await fetch("/api/v1/notifications", { credentials: "same-origin" })
  const payload = (await response.json()) as { notifications?: StatusNotice[] }
  return payload.notifications ?? []
}

export function SchedulePage() {
  const { projectId = "" } = useParams()
  const [enabled, setEnabled] = useState(true)
  const [notify, setNotify] = useState(true)
  const [sessionId, setSessionId] = useState("")
  const notices = useQuery({ queryKey: ["notifications"], queryFn: loadNotices })
  const job = { id: projectId || "schedule", enabled, notify }
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <h1>调度</h1>
      <form
        className="mt-3 flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void csrfToken().then((token) =>
            fetch("/api/v1/schedules", {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "content-type": "application/json",
                "x-csrf-token": token,
              },
              body: JSON.stringify({
                project_id: projectId,
                session_id: sessionId,
                notify,
                enabled,
                rule: { kind: "interval", every: 1, unit: "minutes" },
              }),
            }),
          )
        }}
      >
        <input aria-label="schedule-session" value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
        <label>
          <input
            aria-label="schedule-enabled"
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          启用调度
        </label>
        <label>
          <input
            aria-label="schedule-notify"
            type="checkbox"
            checked={notify}
            onChange={(event) => setNotify(event.target.checked)}
          />
          完成时通知
        </label>
        <button type="submit">保存调度</button>
      </form>
      <section data-schedule data-id={job.id} data-enabled={String(enabled)} data-notify={String(notify)} />
      <ul data-notifications>
        {(notices.data ?? []).map((item) => (
          <li key={item.id}>
            {item.status} {item.run_id}
          </li>
        ))}
      </ul>
    </main>
  )
}
