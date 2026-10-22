import { useState } from "react"

import { IconSpinner } from "../../components/icons"

// “思考过程”折叠块：intermediate delta（reasoning/progress）的累积文本。
// 运行中默认展开并带“正在思考…”微光；终态收口为可点开的折叠块。
// open 为 null = 跟随 active（运行中开、结束后合），一旦点过就以用户为准。
export function ThinkingBlock({ text, active }: { text: string; active: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null)
  const isOpen = open ?? active
  return (
    <div
      data-thinking
      data-thinking-status={active ? "active" : "complete"}
      className="rounded-lg border border-border bg-card"
    >
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setOpen(!isOpen)}
        className={
          "flex w-full items-center gap-1.5 rounded-lg px-3 py-2 text-left " +
          "text-xs text-muted hover:bg-sidebar"
        }
      >
        <span
          aria-hidden="true"
          className={
            "inline-block shrink-0 transition-transform " + (isOpen ? "rotate-90" : "")
          }
        >
          ▸
        </span>
        <span>thoughts</span>
        {active ? (
          <span className="rxy-pulse ml-1 flex items-center gap-1 text-muted-ink">
            <IconSpinner size={11} />
            正在思考…
          </span>
        ) : null}
      </button>
      {isOpen ? (
        <div
          className={
            "mx-3 mb-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words " +
            "rounded-md bg-sidebar p-3 text-xs leading-relaxed text-muted-ink"
          }
        >
          {text}
        </div>
      ) : null}
    </div>
  )
}
