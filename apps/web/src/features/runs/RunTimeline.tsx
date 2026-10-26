import { useEffect, useRef } from "react"

import type { RunSummary } from "../../sdk/client"
import { Timeline } from "../timeline/Timeline"
import { signalFromRunView } from "../feedback/useAutoFeedbackPrompt"
import type { RunTerminalSignal } from "../feedback/autoPrompt"
import { useRunEvents } from "./useRunEvents"
import { isTerminalRunStatus } from "./status"

// W9-F4 真时间线：run.created→user、delta→text、tool.*→工具行、
// approval/question→交互卡、assistant.final→Markdown。已结束的 run
// 只回放一次（follow=0），活跃 run 走 SSE。
export function RunTimeline({
  run,
  onTerminal,
}: {
  run: RunSummary
  // v1.4.6 自动反馈询问：挂载期间观察到 非终态→终态 的真实转换时上报
  // （历史回放 run.status 一开始就是终态，不会触发）。
  onTerminal?: (signal: RunTerminalSignal) => void
}) {
  const { view, connected, notFound, cursorExpired, snapshotSeq } = useRunEvents(
    run.run_id,
    run.status,
  )
  const prevStatusRef = useRef(run.status)
  // 事件流里出现过 cancel_requested 才算“用户点了停止”——终态
  // cancelled 也可能是系统取消（配额/超时），不算 user_stopped。
  const sawCancelRequestedRef = useRef(false)
  useEffect(() => {
    const prev = prevStatusRef.current
    const status = view.status
    prevStatusRef.current = status
    if (status === "cancel_requested" || prev === "cancel_requested") {
      sawCancelRequestedRef.current = true
    }
    if (!isTerminalRunStatus(prev) && isTerminalRunStatus(status) && onTerminal) {
      onTerminal(signalFromRunView(run, view, sawCancelRequestedRef.current))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.status])
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
