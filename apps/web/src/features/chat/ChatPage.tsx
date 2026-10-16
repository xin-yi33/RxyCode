import { useState } from "react"
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
  const [reported, setReported] = useState("")
  const [steerText, setSteerText] = useState("")
  const statusText = reported || live.projection.runStatus || "未知"
  if (live.cursorExpired) {
    return (
      <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
        <RunStatusBanner runId={runId} onStatus={setReported} />
        <p role="alert">重新同步 {live.snapshotSeq ?? ""}</p>
      </main>
    )
  }
  const { projection } = live
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <RunStatusBanner runId={runId} onStatus={setReported} />
      <p data-connection={live.connected ? "open" : "closed"} data-run-status={live.projection.runStatus}>
        {statusText}
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
      <AgentTree
        agents={projection.agents}
        nodes={projection.agents.map((agent) => ({
          id: agent.id,
          parent_id: agent.parent_id ?? "",
          role: agent.name,
          status: agent.status,
          tokens: agent.tokens ?? 0,
        }))}
        finalText={projection.answer}
        steerText={steerText}
        onSteerText={setSteerText}
        onSteer={(text) => {
          const command = text.trim()
          if (!command) return
          const bridge = (window as Window & {
            rxySteer?: (runId: string, text: string) => void
          }).rxySteer
          if (bridge) bridge(runId, command)
        }}
        onCancel={(id) => {
          const bridge = (window as Window & {
            rxyCancelChild?: (runId: string, id: string) => void
          }).rxyCancelChild
          if (bridge) bridge(runId, id)
        }}
      />
      <ArtifactPanel runId={runId} />
    </main>
  )
}
