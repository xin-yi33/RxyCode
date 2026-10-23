import { useState } from "react"

import { IconChevronDown, IconSpinner } from "../../components/icons"

// 「思考过程」块：标题行（chevron + 步数 + 进行中状态）+ 可展开的思维链
// 原文。文本来自 assistant.delta channel=reasoning 的累积，默认收起，
// 点击标题展开查看完整推理；运行中默认收起但不打断滚动。
export function ThinkingBlock({
  steps,
  active,
  text,
}: {
  steps: number
  active: boolean
  text: string
}) {
  const [open, setOpen] = useState(false)
  const expandable = text.length > 0
  const header = (
    <>
      {active ? (
        <>
          <IconSpinner size={11} className="rxy-pulse" />
          <span>正在思考…</span>
        </>
      ) : (
        <span>思考过程</span>
      )}
      {steps > 1 ? <span className="text-muted-ink">（{steps} 步）</span> : null}
      {expandable ? (
        <IconChevronDown
          size={12}
          className={
            "ml-auto shrink-0 transition-transform " + (open ? "rotate-180" : "")
          }
        />
      ) : null}
    </>
  )
  return (
    <div
      data-thinking
      data-thinking-status={active ? "active" : "complete"}
      className="rounded-lg border border-border bg-card text-xs text-muted"
    >
      {expandable ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left"
        >
          {header}
        </button>
      ) : (
        <div className="flex w-full items-center gap-2 px-3 py-2 text-left">
          {header}
        </div>
      )}
      {open && text ? (
        <pre
          className={
            "max-h-96 overflow-y-auto whitespace-pre-wrap break-all " +
            "border-t border-border px-3 py-2 font-mono text-muted-ink"
          }
        >
          {text}
        </pre>
      ) : null}
    </div>
  )
}
