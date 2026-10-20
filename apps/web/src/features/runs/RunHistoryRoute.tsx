import { useQuery } from "@tanstack/react-query"
import { Navigate, useParams } from "react-router"

import { Button } from "../../components/ui/button"
import { createClient } from "../../sdk/client"

const api = createClient()

// /runs/:runId compatibility route (W9-F1 table): resolve the run, then send
// the user to the owning session page where the run card lives.
export function RunHistoryRoute() {
  const { runId = "" } = useParams()
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: ({ signal }) => api.getRun(runId, signal),
  })
  if (run.isPending) {
    return <p className="p-6 text-sm text-muted">正在打开任务…</p>
  }
  if (run.isError) {
    return (
      <section role="alert" className="p-6">
        <p className="text-sm text-muted">任务不存在或暂时不可用。</p>
        <Button className="mt-3" size="sm" onClick={() => void run.refetch()}>
          重试
        </Button>
      </section>
    )
  }
  return (
    <Navigate
      to={`/app/s/${run.data?.session_id ?? ""}#run-${runId}`}
      replace
    />
  )
}
