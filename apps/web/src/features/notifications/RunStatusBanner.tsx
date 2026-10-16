import { useEffect, useRef, useState } from "react"

import "../../app/responsive.css"

export function RunStatusBanner({ runId }: { runId: string }) {
  const openerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    const probe = async () => {
      try {
        const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}`, {
          credentials: "same-origin",
          headers: { accept: "application/json" },
        })
        if (!cancelled) setFailed(!response.ok)
      } catch {
        if (!cancelled) setFailed(true)
      }
    }
    void probe()
    return () => {
      cancelled = true
    }
  }, [runId, attempt])

  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const focusable = () =>
      [...dialog.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea")]
    focusable()[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        setOpen(false)
        openerRef.current?.focus()
        return
      }
      if (event.key !== "Tab") return
      const items = focusable()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!(active instanceof HTMLElement) || !dialog.contains(active)) {
        event.preventDefault()
        first.focus()
        return
      }
      if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open])

  if (failed) {
    return (
      <div role="alert">
        <p>连接失败</p>
        <button type="button" onClick={() => setAttempt((current) => current + 1)}>
          重试
        </button>
      </div>
    )
  }

  return (
    <div>
      <p>运行状态以文字显示，不单靠颜色。</p>
      <button ref={openerRef} type="button" onClick={() => setOpen(true)}>
        打开审批
      </button>
      <button type="button">取消</button>
      {open ? (
        <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="审批">
          <button type="button" onClick={() => { setOpen(false); openerRef.current?.focus() }}>
            关闭
          </button>
          <button type="button">返回</button>
        </div>
      ) : null}
    </div>
  )
}
