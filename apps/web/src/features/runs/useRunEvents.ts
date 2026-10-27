import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { loginPathFor } from "../../app/AuthGate"
import { appNavigate } from "../../app/nav"
import { ApiError, createClient } from "../../sdk/client"
import { reduceEvents, type RunEvent, type RunView } from "./eventReducer"
import { isTerminalRunStatus } from "./status"

const api = createClient()

export type LiveRun = {
  view: RunView
  connected: boolean
  notFound: boolean
  cursorExpired: boolean
  snapshotSeq: number | null
  // 自动反馈门（v1.4.6 修复）：loaded = 首批历史事件已回放；
  // terminalViaEvent = 终态来自事件流本身（run.status），不是 /runs 探测。
  // 探测先把 baseStatus 拉成终态、回放未到时 view.status 已是终态但
  // timeline 还是空的 —— 那时打分会误判空回答。
  loaded: boolean
  terminalViaEvent: boolean
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
  signal?: AbortSignal,
): Promise<{ status: number; parsed: ParsedStream | null; snapshotSeq: number | null }> {
  const headers: Record<string, string> = { accept: "text/event-stream" }
  const query = cursor > 0 ? "follow=0" : "after_seq=0&follow=0"
  if (cursor > 0) headers["last-event-id"] = String(cursor)
  const path = `/api/v1/runs/${encodeURIComponent(runId)}/events?${query}`
  const response = await fetch(path, { credentials: "same-origin", headers, signal })
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

// 控制台用的一次性视图：GET run + follow=0 全量回放，不走 SSE。
export async function fetchRunView(
  runId: string,
  signal?: AbortSignal,
): Promise<RunView> {
  const detail = await api.getRun(runId, signal)
  const result = await readEvents(runId, 0, signal)
  const events = result.parsed?.events ?? []
  return reduceEvents(events, String(detail.status ?? ""), 0, runId).view
}

type ProbeState = "ok" | "terminal" | "missing" | "auth" | "fail"

export function useRunEvents(runId: string, seedStatus = ""): LiveRun {
  const queryClient = useQueryClient()
  const [events, setEvents] = useState<RunEvent[]>([])
  const [baseStatus, setBaseStatus] = useState(seedStatus)
  const [connected, setConnected] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [cursorExpired, setCursorExpired] = useState(false)
  const [snapshotSeq, setSnapshotSeq] = useState<number | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [terminalViaEvent, setTerminalViaEvent] = useState(false)

  useEffect(() => {
    let source: EventSource | null = null
    let timer = 0
    let stopped = false // 组件卸载
    let dead = false // 终态/404/游标过期 —— 不再重连
    let cursor = 0
    let attempt = 0
    const seenSeq = new Set<number>()

    setEvents([])
    setBaseStatus(seedStatus)
    setConnected(false)
    setNotFound(false)
    setCursorExpired(false)
    setSnapshotSeq(null)
    setLoaded(false)
    setTerminalViaEvent(false)

    const redirectLogin = () => {
      dead = true
      source?.close()
      // SPA 跳转：整页刷新会丢掉内存里的 Zustand 草稿（PRD §3.3）。
      appNavigate(
        loginPathFor(window.location.pathname, window.location.search),
        { replace: true },
      )
    }

    const markNotFound = () => {
      dead = true
      setNotFound(true)
      setConnected(false)
      source?.close()
    }

    const expire = (snapshot: number | null) => {
      if (dead) return
      dead = true
      setCursorExpired(true)
      setSnapshotSeq(snapshot)
      setEvents([])
      setConnected(false)
      source?.close()
    }

    // 终态：补拉一次 follow=0 全量回放，然后彻底关闭。
    const finish = async () => {
      if (dead || stopped) return
      dead = true
      source?.close()
      setConnected(false)
      try {
        const result = await readEvents(runId, 0)
        if (stopped) return
        if (result.status === 409 || result.parsed?.expired) {
          expire(result.snapshotSeq ?? result.parsed?.snapshotSeq ?? null)
          return
        }
        if (result.parsed) remember(result.parsed.events)
      } catch {
        // 网络抖动 —— 保留已收到的事件，不再重连。
      }
      void queryClient.invalidateQueries({ queryKey: ["sessionRuns"] })
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
    }

    const remember = (batch: RunEvent[]) => {
      const fresh = batch.filter(
        (event) =>
          Number.isInteger(event.seq) && event.seq >= 1 && !seenSeq.has(event.seq),
      )
      if (fresh.length === 0) return
      let hitTerminal = false
      for (const event of fresh) {
        seenSeq.add(event.seq)
        if (
          event.type === "run.status" &&
          isTerminalRunStatus(String(event.payload?.status ?? ""))
        ) {
          hitTerminal = true
        }
      }
      // 游标是连续水位，不是最大值 —— 中间漏掉的 seq 靠重连回放补上。
      while (seenSeq.has(cursor + 1)) cursor += 1
      setEvents((current) => [...current, ...fresh])
      setLoaded(true)
      if (hitTerminal) {
        setTerminalViaEvent(true)
        void finish()
      }
    }

    // 每次重连前先 GET /runs/{id}：401 跳登录、404 任务不存在、终态收尾。
    const probe = async (): Promise<ProbeState> => {
      try {
        const detail = await api.getRun(runId)
        if (stopped || dead) return "fail"
        setBaseStatus(String(detail.status ?? ""))
        return isTerminalRunStatus(String(detail.status ?? "")) ? "terminal" : "ok"
      } catch (error) {
        if (error instanceof ApiError) {
          if (error.status === 401) return "auth"
          if (error.status === 404) return "missing"
        }
        return "fail"
      }
    }

    const scheduleRecover = () => {
      if (dead || stopped || timer) return
      // 退避 1s、2s、4s…最长 30s
      const delay = Math.min(30_000, 1_000 * 2 ** attempt)
      attempt += 1
      timer = window.setTimeout(() => {
        timer = 0
        void recover()
      }, delay)
    }

    const recover = async () => {
      if (dead || stopped) return
      const state = await probe()
      if (dead || stopped) return
      if (state === "auth") return redirectLogin()
      if (state === "missing") return markNotFound()
      if (state === "terminal") return void finish()
      if (state === "fail") return scheduleRecover()
      try {
        const result = await readEvents(runId, cursor)
        if (dead || stopped) return
        if (result.status === 409 || result.parsed?.expired) {
          return expire(result.snapshotSeq ?? result.parsed?.snapshotSeq ?? null)
        }
        if (result.status === 401) return redirectLogin()
        if (result.status === 404) return markNotFound()
        if (!result.parsed) return scheduleRecover()
        remember(result.parsed.events)
        openFollow()
      } catch {
        scheduleRecover()
      }
    }

    const openFollow = () => {
      if (dead || stopped) return
      source?.close()
      const query = cursor > 0 ? `after_seq=${cursor}&follow=1` : "follow=1"
      source = new EventSource(
        `/api/v1/runs/${encodeURIComponent(runId)}/events?${query}`,
      )
      source.onopen = () => {
        attempt = 0
        setConnected(true)
      }
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
          // CURSOR_EXPIRED 等结构化错误帧走 event: error。
          const parsed = parseEventStream(`data: ${data}\n\n`)
          if (parsed.expired) return expire(parsed.snapshotSeq)
          return
        }
        // 连接断开（含服务端在终态后主动结束 follow 流）：关死自带重连，走退避。
        setConnected(false)
        source?.close()
        scheduleRecover()
      })
    }

    const load = async () => {
      const state = await probe()
      if (stopped || dead) return
      if (state === "auth") return redirectLogin()
      if (state === "missing") return markNotFound()
      if (state === "fail") return scheduleRecover()
      try {
        const snapshot = await readEvents(runId, 0)
        if (stopped || dead) return
        if (snapshot.status === 409 || snapshot.parsed?.expired) {
          return expire(snapshot.snapshotSeq ?? snapshot.parsed?.snapshotSeq ?? null)
        }
        if (snapshot.status === 401) return redirectLogin()
        if (snapshot.status === 404) return markNotFound()
        if (snapshot.parsed) remember(snapshot.parsed.events)
        if (state === "terminal") return // 已结束的 run 只拉一次，不订阅
        openFollow()
      } catch {
        scheduleRecover()
      }
    }
    void load()
    return () => {
      stopped = true
      source?.close()
      if (timer) window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const view = useMemo(
    () => reduceEvents(events, baseStatus, 0, runId).view,
    [events, runId, baseStatus],
  )

  return { view, connected, notFound, cursorExpired, snapshotSeq, loaded, terminalViaEvent }
}
