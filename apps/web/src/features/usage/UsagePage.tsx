import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

export type UsageLine = {
  model_id: string
  tokens: number
  amount: string
  cost_kind: string
}

export type UsageStatement = {
  tokens: number
  amount: string
  lines: UsageLine[]
}

export function usageMarkup(statement: UsageStatement): string {
  const lines = statement.lines
    .map(
      (line) =>
        `<li data-model="${line.model_id}" data-kind="${line.cost_kind}">${line.tokens} ${line.amount}</li>`,
    )
    .join("")
  return `<section data-usage data-tokens="${statement.tokens}" data-amount="${statement.amount}">${lines}</section>`
}

async function loadUsage(modelId: string, day: string): Promise<UsageStatement> {
  const params = new URLSearchParams()
  if (modelId) params.set("model_id", modelId)
  if (day) params.set("day", day)
  const response = await fetch(`/api/v1/usage?${params.toString()}`, { credentials: "same-origin" })
  return (await response.json()) as UsageStatement
}

export function UsagePage({ statement }: { statement?: UsageStatement }) {
  const [modelId, setModelId] = useState("")
  const [day, setDay] = useState("")
  const query = useQuery({
    queryKey: ["usage", modelId, day],
    queryFn: () => loadUsage(modelId, day),
    enabled: statement == null,
  })
  const data = statement ?? query.data
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-6">
      <h1>费用</h1>
      <form className="mt-3 flex flex-wrap gap-2">
        <input aria-label="model-filter" value={modelId} onChange={(event) => setModelId(event.target.value)} />
        <input aria-label="day-filter" type="date" value={day} onChange={(event) => setDay(event.target.value)} />
      </form>
      {data ? <div dangerouslySetInnerHTML={{ __html: usageMarkup(data) }} /> : <p>没有费用记录</p>}
    </main>
  )
}
