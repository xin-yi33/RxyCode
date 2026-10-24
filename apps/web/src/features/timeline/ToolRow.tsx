import { useState } from "react"

import { Collapse } from "../../components/Collapse"
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

function DetailSection({ label, text }: { label: string; text: string }) {
  return (
    <div className="mx-1 mb-1">
      <p className="px-1 pb-0.5 text-[11px] text-muted">{label}</p>
      <pre
        className={
          "max-h-80 overflow-y-auto whitespace-pre-wrap break-all rounded " +
          "bg-sidebar p-2 font-mono text-xs text-muted-ink"
        }
      >
        {text}
      </pre>
    </div>
  )
}

// 紧凑工具卡：工具名 chip + 标题 + 状态图标（spinner→对勾/叉）。点击展开
// 参数/结果详情；运行中默认展开，终态默认折叠（点过之后以用户为准）。
// 展开体用共享 Collapse：关闭时保持挂载（流式结果不丢）且不可聚焦。
export function ToolRow({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState<boolean | null>(null)
  const isOpen = open ?? item.status === "running"
  const hasDetail = Boolean(item.args || item.result || item.summary)
  return (
    <div data-tool-id={item.callId} data-tool-status={item.status}>
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setOpen(!isOpen)}
        className={
          "flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left " +
          "text-xs text-muted hover:bg-sidebar"
        }
      >
        <span
          aria-hidden="true"
          className={
            "mt-0.5 inline-block shrink-0 transition-transform " +
            (isOpen ? "rotate-90" : "")
          }
        >
          ▸
        </span>
        <span className="min-w-0 flex-1">
          <span className="mr-1.5 rounded bg-sidebar px-1.5 py-0.5 font-mono text-[11px] text-muted-ink">
            {item.tool || "tool"}
          </span>
          {item.title ? (
            <span className="break-all text-muted">{item.title}</span>
          ) : null}
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1">
          <StatusIcon status={item.status} />
          <span>{STATUS_TEXT[item.status]}</span>
          {item.exitCode !== undefined ? (
            <span className="text-muted-ink">exit {item.exitCode}</span>
          ) : null}
          {item.durationMs !== undefined ? (
            <span className="text-muted-ink">{item.durationMs} ms</span>
          ) : null}
        </span>
      </button>
      <Collapse open={isOpen}>
        <div className="pb-1">
          {item.args ? <DetailSection label="参数" text={item.args} /> : null}
          {item.result ? (
            <DetailSection label="结果" text={item.result} />
          ) : item.summary ? (
            <DetailSection label="结果" text={item.summary} />
          ) : null}
          {!hasDetail && item.status === "running" ? (
            <p className="px-1 pb-0.5 text-[11px] text-muted">等待工具返回…</p>
          ) : null}
        </div>
      </Collapse>
    </div>
  )
}
