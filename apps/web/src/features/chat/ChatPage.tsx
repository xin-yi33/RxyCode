import { useParams } from "react-router"

import { useRunEvents } from "../runs/useRunEvents"

export function ChatPage() {
  const { runId = "" } = useParams()
  const live = useRunEvents(runId)
  if (live.cursorExpired) {
    return (
      <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
        <p role="alert">重新同步 {live.snapshotSeq ?? ""}</p>
      </main>
    )
  }
  const { projection } = live
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <p data-connection={live.connected ? "open" : "closed"}>
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
    </main>
  )
}
