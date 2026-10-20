import { useRunEvents } from "./useRunEvents"
import { runStatusKind, runStatusText } from "./status"

// W9-F3 placeholder timeline. Props { runId, live } are stable — F4 replaces
// the internals with the full event projection (tools, approvals, questions,
// plan, agents, usage). The data-* attributes below keep the W3 replay
// contract assertable in the meantime.
export function RunTimeline({ runId, live }: { runId: string; live: boolean }) {
  if (!live) return null
  return <LiveTimeline runId={runId} />
}

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

function LiveTimeline({ runId }: { runId: string }) {
  const { projection, connected, cursorExpired, snapshotSeq } = useRunEvents(runId)
  const status = projection.runStatus
  if (cursorExpired) {
    return (
      <p role="alert" className="mt-2 text-sm text-failure">
        重新同步 {snapshotSeq ?? ""}
      </p>
    )
  }
  return (
    <div className="mt-2 space-y-2 text-sm">
      <p className="flex items-center gap-2 text-xs text-muted">
        <span
          className={
            "rounded-full px-2 py-0.5 " + chipClass[runStatusKind(status)]
          }
          data-run-status={status}
        >
          {runStatusText(status)}
        </span>
        <span className={connected ? "text-success-ink" : "text-muted-ink"}>
          {connected ? "已连接" : "重连中…"}
        </span>
      </p>
      {projection.answer ? (
        <p data-answer className="whitespace-pre-wrap leading-relaxed">
          {projection.answer}
        </p>
      ) : null}
      {projection.tools.length > 0 ? (
        <ul className="space-y-1 text-xs text-muted">
          {projection.tools.map((tool, index) => (
            <li
              key={`${tool.callId}-${index}`}
              data-tool-id={tool.callId}
              data-tool-status={tool.status}
            >
              {tool.name} · {tool.status === "failed" ? "失败" : "完成"}
            </li>
          ))}
        </ul>
      ) : null}
      {projection.approvals.length > 0 ? (
        <ul className="space-y-1 text-xs">
          {projection.approvals.map((item) => (
            <li
              key={item.id}
              data-approval-id={item.id}
              className="text-waiting-ink"
            >
              {item.status === "pending" ? "等待审批" : item.status}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
