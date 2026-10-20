import { useEffect, useLayoutEffect, useRef, useState } from "react"

import { IconArrowDown } from "../../components/icons"
import { ApprovalItem } from "../approvals/ApprovalItem"
import { QuestionItem } from "../approvals/QuestionItem"
import {
  isActiveRunStatus,
  runStatusKind,
  runStatusText,
} from "../runs/status"
import type { RunView } from "../runs/eventReducer"
import { Markdown } from "./Markdown"
import { ToolRow } from "./ToolRow"

const chipClass: Record<string, string> = {
  running: "bg-running/15 text-running-ink",
  waiting: "bg-waiting/15 text-waiting-ink",
  success: "bg-success/15 text-success-ink",
  failure: "bg-failure/15 text-failure-ink",
  idle: "bg-border text-muted-ink",
}

export function StatusChip({ status }: { status: string }) {
  return (
    <span
      data-run-status={status}
      className={
        "shrink-0 rounded-full px-2 py-0.5 text-xs " +
        chipClass[runStatusKind(status)]
      }
    >
      {runStatusText(status)}
    </span>
  )
}

function findScroller(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null
  while (current) {
    const overflowY = getComputedStyle(current).overflowY
    if (overflowY === "auto" || overflowY === "scroll") return current
    current = current.parentElement
  }
  return null
}

// §5.4 时间线：顶部状态行（activity + 状态芯片）+ 按 seq 排好的 items。
export function Timeline({
  view,
  connected,
  createdAt,
}: {
  view: RunView
  connected?: boolean
  createdAt?: string | null
}) {
  const listRef = useRef<HTMLOListElement>(null)
  const scrollerRef = useRef<HTMLElement | null>(null)
  const atBottomRef = useRef(true)
  const [hasNew, setHasNew] = useState(false)

  const active = isActiveRunStatus(view.status)

  // 找到滚动祖先（ConsoleShell 的 <main>）并跟踪“是否在底部”。
  useEffect(() => {
    const scroller = findScroller(listRef.current)
    scrollerRef.current = scroller
    if (!scroller) return
    const onScroll = () => {
      const atBottom =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80
      atBottomRef.current = atBottom
      if (atBottom) setHasNew(false)
    }
    scroller.addEventListener("scroll", onScroll, { passive: true })
    onScroll()
    return () => scroller.removeEventListener("scroll", onScroll)
  }, [])

  // 新事件到达：在底部则跟随滚动；否则浮出“↓ 新消息”。
  useLayoutEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    if (atBottomRef.current) {
      scroller.scrollTop = scroller.scrollHeight
    } else {
      setHasNew(true)
    }
  }, [view.timeline, view.activity, view.status])

  const scrollToLatest = () => {
    const scroller = scrollerRef.current
    if (!scroller) return
    scroller.scrollTop = scroller.scrollHeight
    atBottomRef.current = true
    setHasNew(false)
  }

  return (
    <div>
      <p className="flex items-center gap-2 text-xs text-muted">
        <StatusChip status={view.status} />
        {active && view.activity ? (
          <span className="min-w-0 truncate" data-activity>
            {view.activity}
          </span>
        ) : null}
        {active && connected === false ? (
          <span className="shrink-0 text-muted-ink">重连中…</span>
        ) : null}
        {createdAt ? (
          <time
            dateTime={createdAt}
            className="ml-auto shrink-0 text-muted-ink"
          >
            {new Date(createdAt).toLocaleString()}
          </time>
        ) : null}
      </p>
      <ol ref={listRef} className="relative mt-3 space-y-3">
        {view.timeline.map((item) => {
          const key = `${item.kind}-${item.seq}`
          switch (item.kind) {
            case "user":
              return (
                <li key={key} className="flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-bubble px-4 py-2 text-sm leading-relaxed">
                    {item.text}
                  </p>
                </li>
              )
            case "text":
              return (
                <li key={key}>
                  <Markdown text={item.text} />
                </li>
              )
            case "tool":
              return (
                <li key={key}>
                  <ToolRow item={item} />
                </li>
              )
            case "approval":
              return (
                <li key={key}>
                  <ApprovalItem runId={view.runId} item={item} />
                </li>
              )
            case "question":
              return (
                <li key={key}>
                  <QuestionItem runId={view.runId} item={item} />
                </li>
              )
            case "final":
              return (
                <li key={key} data-answer>
                  <Markdown text={item.text} />
                </li>
              )
            default:
              return null
          }
        })}
        {hasNew ? (
          // sticky 在列表末尾：向上滚动时浮在滚动口底部（输入框上方），点击回底。
          <li className="sticky bottom-36 z-10 flex justify-end">
            <button
              type="button"
              onClick={scrollToLatest}
              className={
                "flex items-center gap-1 rounded-full border border-border " +
                "bg-card px-3 py-1.5 text-xs text-foreground shadow-sm"
              }
            >
              <IconArrowDown size={13} />
              新消息
            </button>
          </li>
        ) : null}
      </ol>
    </div>
  )
}
