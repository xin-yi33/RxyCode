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
    void client.terminal(sessionId).then(async (session) => {
      if (disposed || host.current === null) return
      setScrollback(session.scrollback)
      const { Terminal } = await import("@xterm/xterm")
      if (disposed || host.current === null) return
      const next = new Terminal({ convertEol: true, fontSize: 14, rows: 16, cols: 80 })
      next.open(host.current)
      if (session.scrollback) next.write(session.scrollback)
      term = next
    })
    return () => {
      disposed = true
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
