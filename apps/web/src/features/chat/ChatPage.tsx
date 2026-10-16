import { useParams } from "react-router"

import { AgentTree } from "../agents/AgentTree"
import { ApprovalCard } from "../approvals/ApprovalCard"
import { ArtifactPanel } from "../artifacts/ArtifactPanel"
import { RunStatusBanner } from "../notifications/RunStatusBanner"
import { PlanDock } from "../plan/PlanDock"
import { useRunEvents } from "../runs/useRunEvents"

export function ChatPage() {
  const { runId = "" } = useParams()
  const live = useRunEvents(runId)
  if (live.cursorExpired) {
    return (
      <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
        <RunStatusBanner runId={runId} />
        <p role="alert">重新同步 {live.snapshotSeq ?? ""}</p>
      </main>
    )
  }
  const { projection } = live
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <RunStatusBanner runId={runId} />
      <p data-connection={live.connected ? "open" : "closed"} data-run-status={live.projection.runStatus}>
        {live.connected ? "已连接" : "正在连接"}
      </p>
      <section data-answer>{projection.answer}</section>
      <ul>
        {projection.intermediate.map((text) => (
          <li key={text} data-intermediate>
            {text}
          </li>
        ))}
      </ul>
      <ul>
        {projection.tools.map((tool) => (
          <li key={tool.callId} data-tool-id={tool.callId} data-tool-status={tool.status}>
            {tool.name} {tool.status === "failed" ? "失败" : "完成"}
          </li>
        ))}
      </ul>
      <ul>
        {projection.approvals.map((item) => (
          <li key={item.id} data-approval-id={item.id}>
            {item.status === "pending" ? "等待审批" : item.status}
          </li>
        ))}
      </ul>
      <PlanDock plans={projection.plans} todos={projection.todos} />
      <ApprovalCard
        runId={runId}
        refreshKey={projection.approvals.map((item) => item.id).join(" ")}
        questions={projection.questions}
      />
      <AgentTree agents={projection.agents} />
      <ArtifactPanel runId={runId} />
    </main>
  )
}
