import type { RunSummary } from "../../sdk/client"
import { Timeline } from "../timeline/Timeline"
import { useRunEvents } from "./useRunEvents"

// W9-F4 真时间线：run.created→user、delta→text、tool.*→工具行、
// approval/question→交互卡、assistant.final→Markdown。已结束的 run
// 只回放一次（follow=0），活跃 run 走 SSE。
export function RunTimeline({ run }: { run: RunSummary }) {
  const { view, connected, notFound, cursorExpired, snapshotSeq } = useRunEvents(
    run.run_id,
    run.status,
  )
  if (notFound) {
    return (
      <p role="alert" className="mt-2 text-sm text-failure">
        任务不存在
      </p>
    )
  }
  if (cursorExpired) {
    return (
      <p role="alert" className="mt-2 text-sm text-failure">
        重新同步 {snapshotSeq ?? ""}
      </p>
    )
  }
  const hasOutput = view.timeline.some(
    (item) => item.kind === "text" || item.kind === "final",
  )
  return (
    <div>
      <Timeline view={view} connected={connected} createdAt={run.created_at} />
      {!hasOutput && run.final_preview ? (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
          {run.final_preview}
        </p>
      ) : null}
    </div>
  )
}
