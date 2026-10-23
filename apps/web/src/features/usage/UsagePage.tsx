import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

export type UsageLine = {
  model_id: string
  tokens: number
  amount: string
  cost_kind: string
  // Server rows carry the owning run id; hand-built statements may omit it.
  run_id?: string
}

export type UsageStatement = {
  tokens: number
  amount: string
  lines: UsageLine[]
}

// Same threshold as rxycode_server.metrics.ABNORMAL_COST_USD: a billed run
// above $1 is surfaced, never averaged into the total invisibly.
export const ABNORMAL_COST_USD = 1

export function abnormalCost(amount: string): boolean {
  return Number(amount) > ABNORMAL_COST_USD
}

export type RunEventRow = {
  seq: number
  type: string
  payload: Record<string, unknown>
}

export type TraceLayer = { count: number; duration_ms: number }

export type RunTrace = {
  trace_id: string
  // The run's execution trace set: only spans FULLY inside the terminal
  // boundary contribute — a post-terminal retry keeps its own fresh
  // trace_id visible in its post_terminal entry, never here.
  trace_ids: string[]
  span_count: number
  layers: Record<string, TraceLayer>
  // Honest duration accounting: elapsed is the trace envelope —
  // min(start_epoch) -> max(end_epoch) — but only over spans inside the
  // run's terminal boundary (the worker.run span's own end_epoch; the
  // http/server root ends at create-commit, long before the async worker
  // finishes, so a root-span duration would under-report while a
  // post-terminal span would over-report). Summed span durations are
  // reported separately as total_span_work_ms — nested spans never
  // double-count as elapsed time.
  elapsed_ms: number
  total_span_work_ms: number
  // Real telemetry outside the terminal boundary (e.g. an idempotent
  // create_run retry's http span, marked run.idempotent_retry or simply
  // still exporting when the run committed): observable, counted in
  // span_count/layers, but excluded from elapsed_ms and trace_ids.
  post_terminal: Record<string, unknown>[]
  tool_calls: string[]
  events_url: string
  cache_hits: number
  cache_misses: number
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

// The events endpoint streams SSE frames (`id:` + `data: {seq,type,payload}`).
// A non-follow fetch replays the whole retained log and closes, so one fetch
// is enough to reconstruct the run's telemetry.span rows client-side.
export function parseRunEvents(sse: string): RunEventRow[] {
  const events: RunEventRow[] = []
  for (const line of sse.split("\n")) {
    if (!line.startsWith("data: ")) continue
    try {
      const parsed = JSON.parse(line.slice(6)) as RunEventRow
      if (parsed && typeof parsed.type === "string") events.push(parsed)
    } catch {
      // A malformed frame never breaks the rest of the stream.
    }
  }
  return events
}

export function traceSummary(runId: string, events: RunEventRow[]): RunTrace | null {
  // Only payloads carrying a trace_id count as spans (the same
  // _is_span_payload gate rxycode_server.metrics applies).
  const spans = events
    .filter((event) => event.type === "telemetry.span")
    .map((event) => event.payload || {})
    .filter((span) => Boolean(span.trace_id))
  if (spans.length === 0) return null
  const layers: Record<string, TraceLayer> = {}
  const toolCalls: string[] = []
  let cacheHits = 0
  let cacheMisses = 0
  for (const span of spans) {
    const kind = String(span.kind || "internal")
    const slot = layers[kind] ?? (layers[kind] = { count: 0, duration_ms: 0 })
    slot.count += 1
    slot.duration_ms += Number(span.duration_ms || 0)
    if (typeof span.tool_call_id === "string" && span.tool_call_id) {
      toolCalls.push(span.tool_call_id)
    }
    const attrs = (span.attrs || {}) as Record<string, unknown>
    cacheHits += Number(attrs["cache.hits"] || 0)
    cacheMisses += Number(attrs["cache.misses"] || 0)
  }
  // Terminal boundary — mirrors metrics._terminal_boundary: the
  // worker.run span's own end_epoch, finalized inside the terminal
  // commit. A span counts toward the run's execution window only when it
  // is FULLY inside that boundary — start AND end at/before it — and is
  // not an explicitly-marked idempotent retry: a retry's http span can
  // start after the run ended or start inside the window yet keep
  // exporting past it, and counting its far end would stretch a 120ms
  // run into a 60s one (mirrors metrics._in_window). With no boundary the
  // run never emitted a worker span, so nothing bounds the envelope.
  const workerEnds = spans
    .filter((span) => span.name === "worker.run")
    .map((span) => Number(span.end_epoch || 0))
    .filter((end) => end > 0)
  const boundary = workerEnds.length > 0 ? Math.max(...workerEnds) : null
  const inWindow: Record<string, unknown>[] = []
  const postTerminal: Record<string, unknown>[] = []
  for (const span of spans) {
    const attrs = (span.attrs || {}) as Record<string, unknown>
    const inside =
      !attrs["run.idempotent_retry"] &&
      (boundary === null ||
        (Number(span.start_epoch || 0) <= boundary &&
          Number(span.end_epoch || 0) <= boundary))
    if (inside) {
      inWindow.push(span)
    } else {
      postTerminal.push(span)
    }
  }
  // Run elapsed is the trace envelope — min(start) -> max(end) — over the
  // in-window spans only; post-terminal spans stay observable under
  // post_terminal (and in span_count/layers — real work, honestly
  // counted) but never stretch the envelope or claim the run's trace set.
  let elapsedMs = 0
  if (inWindow.length > 0) {
    const starts = inWindow.map((span) => Number(span.start_epoch || 0))
    const ends = inWindow.map((span) => Number(span.end_epoch || 0))
    elapsedMs = Math.max(0, (Math.max(...ends) - Math.min(...starts)) * 1000)
  }
  const traceIds = [
    ...new Set(inWindow.map((span) => String(span.trace_id || ""))),
  ]
    .filter((id) => id.length > 0)
    .sort()
  const totalSpanWorkMs = spans.reduce(
    (total, span) => total + Number(span.duration_ms || 0),
    0,
  )
  return {
    trace_id: traceIds[0] ?? "",
    trace_ids: traceIds,
    span_count: spans.length,
    layers,
    elapsed_ms: elapsedMs,
    total_span_work_ms: totalSpanWorkMs,
    post_terminal: postTerminal,
    tool_calls: toolCalls,
    events_url: `/api/v1/runs/${runId}/events`,
    cache_hits: cacheHits,
    cache_misses: cacheMisses,
  }
}

export function usageMarkup(statement: UsageStatement): string {
  const lines = statement.lines
    .map((line) => {
      const base = `${escapeHtml(line.model_id)} ${escapeHtml(line.cost_kind)} ${line.tokens} ${escapeHtml(line.amount)}`
      if (!line.run_id) return base
      const abnormal = abnormalCost(line.amount) ? " data-abnormal" : ""
      return `${base} <a data-trace${abnormal} href="/api/v1/runs/${escapeHtml(line.run_id)}/events">trace</a>`
    })
    .join("\n")
  return `<section data-usage data-tokens="${statement.tokens}" data-amount="${statement.amount}">${lines}</section>`
}

async function loadUsage(modelId: string, day: string): Promise<UsageStatement> {
  const params = new URLSearchParams()
  if (modelId) params.set("model_id", modelId)
  if (day) params.set("day", day)
  const response = await fetch(`/api/v1/usage?${params.toString()}`, { credentials: "same-origin" })
  return (await response.json()) as UsageStatement
}

async function loadRunEvents(runId: string): Promise<RunEventRow[]> {
  const response = await fetch(`/api/v1/runs/${runId}/events`, {
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" },
  })
  if (!response.ok) throw new Error(`run events ${response.status}`)
  return parseRunEvents(await response.text())
}

// Lazy per-run trace: opens on demand, replays the tenant-scoped event log,
// and shows the correlated OTel spans the run journaled. A foreign tenant's
// run 404s before any span leaves the server.
function RunTraceRow({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ["run-trace", runId],
    queryFn: () => loadRunEvents(runId),
    enabled: open,
    retry: false,
  })
  const trace = query.data ? traceSummary(runId, query.data) : null
  return (
    <details data-trace-run={runId} onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary>trace</summary>
      {query.isLoading ? <span>loading…</span> : null}
      {query.isError ? <span>trace unavailable</span> : null}
      {trace ? (
        <section data-trace-summary>
          <p>
            trace_id <code>{trace.trace_id}</code> · {trace.span_count} spans ·
            elapsed {trace.elapsed_ms.toFixed(1)} ms · span work{" "}
            {trace.total_span_work_ms.toFixed(1)} ms
          </p>
          <ul>
            {Object.entries(trace.layers).map(([kind, stat]) => (
              <li key={kind} data-layer={kind}>
                {kind} ×{stat.count} · {stat.duration_ms.toFixed(1)} ms
              </li>
            ))}
          </ul>
          {trace.tool_calls.length > 0 ? <p>tools: {trace.tool_calls.join(", ")}</p> : null}
          {trace.cache_hits + trace.cache_misses > 0 ? (
            <p>
              cache: {trace.cache_hits} hits / {trace.cache_misses} misses
            </p>
          ) : null}
          {trace.post_terminal.length > 0 ? (
            <p data-post-terminal>
              post-terminal:{" "}
              {trace.post_terminal
                .map((span) => String(span.name || "span"))
                .join(", ")}
            </p>
          ) : null}
          <a href={trace.events_url}>raw events</a>
        </section>
      ) : null}
      {query.isSuccess && !trace ? <span>no spans journaled</span> : null}
    </details>
  )
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
      {data ? (
        <section data-usage data-tokens={data.tokens} data-amount={data.amount}>
          <p>
            {data.tokens} {data.amount}
          </p>
          <ul>
            {data.lines.map((line) => (
              <li key={`${line.model_id}-${line.cost_kind}`}>
                {line.model_id} {line.cost_kind} {line.tokens} {line.amount}
                {abnormalCost(line.amount) ? <strong data-abnormal> abnormal</strong> : null}
                {line.run_id ? <RunTraceRow runId={line.run_id} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <p>没有费用记录</p>
      )}
    </main>
  )
}
