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
  const {
    view,
    connected,
    notFound,
    cursorExpired,
    snapshotSeq,
    loaded,
    terminalViaEvent,
  } = useRunEvents(run.run_id, run.status)
  // 挂载时的种子终态 = 历史回放 run —— 永不触发自动询问。
  const seedWasTerminalRef = useRef(isTerminalRunStatus(run.status))
  const firedRef = useRef(false)
  // 事件流里出现过 cancel_requested 才算“用户点了停止”——终态
  // cancelled 也可能是系统取消（配额/超时），不算 user_stopped。
  const sawCancelRequestedRef = useRef(false)
  useEffect(() => {
    const status = view.status
    if (status === "cancel_requested") {
      sawCancelRequestedRef.current = true
    }
    if (
      !firedRef.current &&
      !seedWasTerminalRef.current &&
      isTerminalRunStatus(status) &&
      onTerminal &&
      loaded &&
      terminalViaEvent
    ) {
      // 只报「事件流自己送到的终态 + 历史回放已完成」—— /runs 探测先把
      // baseStatus 拉成终态而事件未回放时，timeline 为空会把 succeeded
      // 误判成空回答（empty_answer 假阳性）；回放落地后此处仍会触发。
      firedRef.current = true
      onTerminal(signalFromRunView(run, view, sawCancelRequestedRef.current))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.status, loaded, terminalViaEvent])
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
