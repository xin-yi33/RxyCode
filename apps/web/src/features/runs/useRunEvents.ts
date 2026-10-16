import { useEffect, useState } from "react"

import { reduceEvents, type Projection, type RunEvent } from "./eventReducer"

export type LiveRun = {
  projection: Projection
  cursorExpired: boolean
  snapshotSeq: number | null
  connected: boolean
}

function parseFrames(text: string): RunEvent[] {
  const events: RunEvent[] = []
  for (const block of text.split("\n\n")) {
    const dataLine = block.split("\n").find((line) => line.startsWith("data:"))
    if (!dataLine) continue
    try {
      const body = JSON.parse(dataLine.slice(5).trim()) as RunEvent & { code?: string }
      if (body.code || typeof body.seq !== "number") continue
      events.push({ seq: body.seq, type: body.type, payload: body.payload ?? {} })
    } catch {
      continue
    }
  }
  return events
}

export function useRunEvents(runId: string): LiveRun {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [cursorExpired, setCursorExpired] = useState(false)
  const [snapshotSeq, setSnapshotSeq] = useState<number | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let source: EventSource | null = null
    let stopped = false
    const load = async () => {
      const path = `/api/v1/runs/${encodeURIComponent(runId)}/events?after_seq=0&follow=0`
      const response = await fetch(path, {
        credentials: "same-origin",
        headers: { accept: "text/event-stream" },
      })
      if (stopped) return
      if (response.status === 409) {
        const body = (await response.json()) as { code?: string; snapshot_seq?: number }
        if (body.code === "CURSOR_EXPIRED") {
          setCursorExpired(true)
          setSnapshotSeq(typeof body.snapshot_seq === "number" ? body.snapshot_seq : null)
          setEvents([])
        }
        return
      }
      if (!response.ok) return
      const snapshot = parseFrames(await response.text())
      if (stopped) return
      setEvents(snapshot)
      setConnected(true)
      source = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events?follow=1`)
      source.onmessage = (message) => {
        try {
          const body = JSON.parse(message.data) as RunEvent
          if (typeof body.seq !== "number") return
          setEvents((current) => [...current, { ...body, payload: body.payload ?? {} }])
        } catch {
          return
        }
      }
      source.addEventListener("error", (event) => {
        const data = (event as MessageEvent).data
        if (typeof data !== "string") {
          setConnected(false)
          return
        }
        try {
          const body = JSON.parse(data) as { code?: string; snapshot_seq?: number }
          if (body.code !== "CURSOR_EXPIRED") return
          setCursorExpired(true)
          setSnapshotSeq(typeof body.snapshot_seq === "number" ? body.snapshot_seq : null)
          setEvents([])
          source?.close()
        } catch {
          setConnected(false)
        }
      })
    }
    void load()
    return () => {
      stopped = true
      source?.close()
    }
  }, [runId])

  return {
    projection: reduceEvents(events),
    cursorExpired,
    snapshotSeq,
    connected,
  }
}
