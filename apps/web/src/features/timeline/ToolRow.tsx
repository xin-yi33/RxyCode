import { useState } from "react"

import { IconCheck, IconClose, IconSpinner } from "../../components/icons"
import type { TimelineItem } from "../runs/eventReducer"

type ToolItem = Extract<TimelineItem, { kind: "tool" }>

const STATUS_TEXT: Record<ToolItem["status"], string> = {
  running: "运行中",
  completed: "完成",
  failed: "失败",
}

function StatusIcon({ status }: { status: ToolItem["status"] }) {
  if (status === "running") {
    return <IconSpinner size={13} className="text-muted" />
  }
  if (status === "completed") {
    return <IconCheck size={13} className="text-success-ink" />
  }
  return <IconClose size={13} className="text-failure-ink" />
}

// 一行灰色小字工具行：▸ {tool} {title} + 状态；点击展开 summary（等宽、20 行内滚动）。
export function ToolRow({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(false)
  const summary = item.summary ?? ""
  return (
    <div data-tool-id={item.callId} data-tool-status={item.status}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={
          "flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left " +
          "font-mono text-xs text-muted hover:bg-sidebar"
        }
      >
        <span
          aria-hidden="true"
          className={
            "mt-0.5 inline-block shrink-0 transition-transform " +
            (open ? "rotate-90" : "")
          }
        >
          ▸
        </span>
        <span className="min-w-0 flex-1">
          <span className="break-all">
            {item.tool}
            {item.title ? ` ${item.title}` : ""}
          </span>
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1">
          <StatusIcon status={item.status} />
          <span>{STATUS_TEXT[item.status]}</span>
          {item.exitCode !== undefined ? (
            <span className="text-muted-ink">exit {item.exitCode}</span>
          ) : null}
        </span>
      </button>
      {open && summary ? (
        <pre
          className={
            "mx-1 mb-1 max-h-80 overflow-y-auto whitespace-pre-wrap break-all " +
            "rounded bg-sidebar p-2 font-mono text-xs text-muted-ink"
          }
        >
          {summary}
        </pre>
      ) : null}
      {item.durationMs !== undefined ? (
        <p className="px-1 pb-0.5 font-mono text-xs text-muted">
          {item.durationMs} ms
        </p>
      ) : null}
    </div>
  )
}
