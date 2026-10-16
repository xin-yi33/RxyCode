import { useEffect, useState } from "react"

import { reduceEvents, type Projection, type RunEvent } from "./eventReducer"

export type LiveRun = {
  projection: Projection
  cursorExpired: boolean
  snapshotSeq: number | null
  connected: boolean
}

type ParsedStream = {
  events: RunEvent[]
  expired: boolean
  snapshotSeq: number | null
}

export function parseEventStream(text: string): ParsedStream {
  const events: RunEvent[] = []
  for (const block of text.split("\n\n")) {
    let data = ""
    for (const line of block.split("\n")) {
      if (line.startsWith("data:")) data += line.slice(5).trim()
    }
    if (!data) continue
    try {
      const body = JSON.parse(data) as {
        seq?: number
        type?: string
        payload?: Record<string, unknown>
        code?: string
        snapshot_seq?: number
      }
      if (body.code === "CURSOR_EXPIRED") {
        const snapshot = body.snapshot_seq
        return {
          events,
          expired: true,
          snapshotSeq: typeof snapshot === "number" ? snapshot : null,
        }
      }
      if (typeof body.seq === "number" && typeof body.type === "string") {
        events.push({ seq: body.seq, type: body.type, payload: body.payload ?? {} })
      }
    } catch {
      continue
    }
  }
  return { events, expired: false, snapshotSeq: null }
}

async function readEvents(
  runId: string,
  cursor: number,
): Promise<{ status: number; parsed: ParsedStream | null; snapshotSeq: number | null }> {
  const headers: Record<string, string> = { accept: "text/event-stream" }
  const query = cursor > 0 ? "follow=0" : "after_seq=0&follow=0"
  if (cursor > 0) headers["last-event-id"] = String(cursor)
  const path = `/api/v1/runs/${encodeURIComponent(runId)}/events?${query}`
  const response = await fetch(path, { credentials: "same-origin", headers })
  if (response.status === 409) {
    const body = (await response.json()) as { snapshot_seq?: number }
    const snapshot = body.snapshot_seq
    return {
      status: 409,
      parsed: null,
      snapshotSeq: typeof snapshot === "number" ? snapshot : null,
    }
  }
  if (!response.ok) return { status: response.status, parsed: null, snapshotSeq: null }
  return { status: 200, parsed: parseEventStream(await response.text()), snapshotSeq: null }
}

export function useRunEvents(runId: string): LiveRun {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [runStatus, setRunStatus] = useState("")
  const [cursorExpired, setCursorExpired] = useState(false)
  const [snapshotSeq, setSnapshotSeq] = useState<number | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let source: EventSource | null = null
    let stopped = false
    let dead = false
    let cursor = 0
    setEvents([])
    setRunStatus("")
    setCursorExpired(false)
    setSnapshotSeq(null)
    setConnected(false)

    const expire = (snapshot: number | null) => {
      if (dead) return
      dead = true
      setCursorExpired(true)
      setSnapshotSeq(snapshot)
      setEvents([])
      setConnected(false)
      source?.close()
    }

    const remember = (batch: RunEvent[]) => {
      if (batch.length === 0) return
      cursor = batch[batch.length - 1].seq
      setEvents((current) => [...current, ...batch])
    }

    const openFollow = () => {
      source?.close()
      const follow = `/api/v1/runs/${encodeURIComponent(runId)}/events?follow=1`
      source = new EventSource(follow)
      source.onopen = () => setConnected(true)
      source.onmessage = (message) => {
        try {
          const body = JSON.parse(message.data) as RunEvent
          if (typeof body.seq !== "number" || typeof body.type !== "string") return
          remember([{ seq: body.seq, type: body.type, payload: body.payload ?? {} }])
          setConnected(true)
        } catch {
          return
        }
      }
      source.addEventListener("error", (event) => {
        if (dead || stopped) return
        const data = (event as MessageEvent).data
        if (typeof data === "string") {
          const parsed = parseEventStream(`data: ${data}\n\n`)
          if (parsed.expired) expire(parsed.snapshotSeq)
          return
        }
        setConnected(false)
        source?.close()
        void readEvents(runId, cursor).then((result) => {
          if (stopped) return
          if (result.status === 409 || result.parsed?.expired) {
            expire(result.snapshotSeq ?? result.parsed?.snapshotSeq ?? null)
            return
          }
          if (result.parsed) remember(result.parsed.events)
          setConnected(true)
          if (!stopped) openFollow()
        })
      })
    }

    const load = async () => {
      const state = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}`, {
        credentials: "same-origin",
        headers: { accept: "application/json" },
      })
      if (stopped) return
      if (state.ok) {
        const body = (await state.json()) as { status?: string }
        setRunStatus(String(body.status ?? ""))
      }
      const snapshot = await readEvents(runId, 0)
      if (stopped) return
      if (snapshot.status === 409 || snapshot.parsed?.expired) {
        expire(snapshot.snapshotSeq ?? snapshot.parsed?.snapshotSeq ?? null)
        return
      }
      if (snapshot.parsed) remember(snapshot.parsed.events)
      setConnected(true)
      openFollow()
    }
    void load()
    return () => {
      stopped = true
      source?.close()
    }
  }, [runId])

  return {
    projection: reduceEvents(events, runStatus),
    cursorExpired,
    snapshotSeq,
    connected,
  }
}
