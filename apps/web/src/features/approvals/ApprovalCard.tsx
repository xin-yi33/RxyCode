import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { ApiError, createClient } from "../../sdk/client"

type Ask = {
  approval_id: string
  tool: string
  arguments?: { path?: string; file?: string }
  deadline?: string | null
  revision: number
}

export function ApprovalCard({ runId }: { runId: string }) {
  const client = createClient()
  const query = useQuery({
    queryKey: ["approvals", runId],
    queryFn: () => client.listApprovals(runId),
  })
  const [conflict, setConflict] = useState(false)

  async function decide(item: Ask, decision: "approved" | "rejected") {
    setConflict(false)
    try {
      await client.decideApproval(runId, {
        approval_id: item.approval_id,
        decision,
        revision: item.revision,
      })
      await query.refetch()
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) setConflict(true)
    }
  }

  return (
    <section>
      {query.data?.approvals.map((item) => {
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
      {conflict ? <p role="alert">冲突</p> : null}
    </section>
  )
}
