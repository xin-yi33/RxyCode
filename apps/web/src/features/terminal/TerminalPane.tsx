import { useEffect, useRef, useState } from "react"
import "@xterm/xterm/css/xterm.css"

import { createClient } from "../../sdk/client"

export function TerminalPane({ sessionId }: { sessionId: string }) {
  const host = useRef<HTMLDivElement>(null)
  const [scrollback, setScrollback] = useState("")

  useEffect(() => {
    const client = createClient()
    let disposed = false
    let term: { dispose: () => void } | null = null
    const disposers: Array<() => void> = []
    void client.terminal(sessionId).then(async (session) => {
      if (disposed || host.current === null) return
      setScrollback(session.scrollback)
      const { Terminal } = await import("@xterm/xterm")
      if (disposed || host.current === null) return
      const next = new Terminal({ convertEol: true, fontSize: 14, rows: 16, cols: 80 })
      next.open(host.current)
      const scheme = window.location.protocol === "https:" ? "wss" : "ws"
      const socket = new WebSocket(
        `${scheme}://${window.location.host}/api/v1/terminals/${encodeURIComponent(sessionId)}/ws`,
      )
      socket.onmessage = (event) => {
        const frame = JSON.parse(String(event.data)) as { type?: string; data?: string }
        if (frame.type === "output" && frame.data) {
          next.write(frame.data)
          setScrollback((current) => current + frame.data)
        }
      }
      socket.onerror = () => {
        if (session.scrollback) next.write(session.scrollback)
      }
      const onData = next.onData((input) => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "input", data: input }))
        }
      })
      const onResize = next.onResize(({ cols, rows }) => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "resize", cols, rows }))
        }
      })
      term = next
      if (disposed) {
        onData.dispose()
        onResize.dispose()
        socket.close()
        next.dispose()
        return
      }
      disposers.push(() => {
        onData.dispose()
        onResize.dispose()
        socket.close()
      })
    })
    return () => {
      disposed = true
      disposers.forEach((dispose) => dispose())
      term?.dispose()
    }
  }, [sessionId])

  return (
    <section className="mx-auto min-h-screen max-w-5xl px-4 py-6">
      <div ref={host} style={{ height: 280 }} />
      <p data-scrollback={sessionId}>{scrollback}</p>
    </section>
  )
}
