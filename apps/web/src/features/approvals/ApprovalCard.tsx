import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { ApiError, createClient } from "../../sdk/client"

type Ask = {
  approval_id: string
  tool: string
  arguments?: { path?: string; file?: string }
  deadline?: string | null
  revision: number
}

export function ApprovalCard({
  runId,
  refreshKey,
  questions,
}: {
  runId: string
  refreshKey: string
  questions: { id: string; prompt: string; answer: string }[]
}) {
  const client = createClient()
  const query = useQuery({
    queryKey: ["approvals", runId, refreshKey],
    queryFn: () => client.listApprovals(runId),
  })
  const [conflict, setConflict] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [shown, setShown] = useState<Ask[]>([])
  useEffect(() => {
    const next = query.data?.approvals
    if (!next || next.length === 0) return
    setShown(next)
  }, [query.data])

  async function decide(item: Ask, decision: "approved" | "rejected") {
    setConflict(false)
    try {
      await client.decideApproval(runId, {
        approval_id: item.approval_id,
        decision,
        revision: item.revision,
      })
      setShown((current) => current.filter((row) => row.approval_id !== item.approval_id))
      await query.refetch()
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) setConflict(true)
    }
  }

  return (
    <section>
      {shown.map((item) => {
        const args = item.arguments ?? {}
        const path = String(args.path ?? args.file ?? "")
        return (
          <article key={item.approval_id} data-approval-card data-approval-id={item.approval_id}>
            <p>{item.tool}</p>
            <p>{path}</p>
            <p>{item.deadline ?? ""}</p>
            <button type="button" onClick={() => void decide(item, "approved")}>
              批准
            </button>
            <button type="button" onClick={() => void decide(item, "rejected")}>
              拒绝
            </button>
          </article>
        )
      })}
      {questions.map((item) => (
        <form
          key={item.id}
          data-question-id={item.id}
          onSubmit={(event) => {
            event.preventDefault()
            void client.answerQuestion(runId, {
              question_id: item.id,
              answer: drafts[item.id] ?? "",
            })
          }}
        >
          <p>{item.prompt}</p>
          <label>
            回答
            <input
              value={item.answer || drafts[item.id] || ""}
              onChange={(event) =>
                setDrafts((current) => ({ ...current, [item.id]: event.target.value }))
              }
            />
          </label>
          <button type="submit">提交</button>
        </form>
      ))}
      {conflict ? <p role="alert">冲突</p> : null}
    </section>
  )
}
