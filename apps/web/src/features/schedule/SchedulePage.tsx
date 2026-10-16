import { useState } from "react"
import { useParams } from "react-router"

export type ScheduleJob = {
  id: string
  enabled: boolean
  notify: boolean
}

export function scheduleMarkup(job: ScheduleJob): string {
  const enabled = job.enabled ? "true" : "false"
  const notify = job.notify ? "true" : "false"
  return `<section data-schedule data-id="${job.id}" data-enabled="${enabled}" data-notify="${notify}"></section>`
}

export function SchedulePage() {
  const { projectId = "" } = useParams()
  const [enabled, setEnabled] = useState(true)
  const [notify, setNotify] = useState(true)
  const job = { id: projectId || "schedule", enabled, notify }
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <h1>调度</h1>
      <label className="mt-3 block">
        <input
          aria-label="schedule-enabled"
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        启用调度
      </label>
      <label className="mt-3 block">
        <input
          aria-label="schedule-notify"
          type="checkbox"
          checked={notify}
          onChange={(event) => setNotify(event.target.checked)}
        />
        完成时通知
      </label>
      <div dangerouslySetInnerHTML={{ __html: scheduleMarkup(job) }} />
    </main>
  )
}
