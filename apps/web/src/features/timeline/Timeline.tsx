import { useEffect, useRef } from "react"

import { Markdown } from "../../components/Markdown"
import { ApprovalItem } from "../approvals/ApprovalItem"
import { QuestionItem } from "../approvals/QuestionItem"
import {
  isActiveRunStatus,
  runStatusKind,
  runStatusText,
} from "../runs/status"
import type { RunView } from "../runs/eventReducer"
import { ThinkingBlock } from "./ThinkingBlock"
import { TasksBlock } from "./TasksBlock"
import { ToolRow } from "./ToolRow"
import "./timeline.css"

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

// §5.4 时间线：顶部状态行（activity + 状态芯片）+ 按 seq 排好的 items。
// 滚动完全交给 SessionPage 的唯一 chat-scroll 容器（useChatScrollController）——
// 这里绝不写祖先 scrollTop，也不自己放 FAB。
export function Timeline({
  view,
  connected,
  createdAt,
}: {
  view: RunView
  connected?: boolean
  createdAt?: string | null
}) {
  const active = isActiveRunStatus(view.status)
  const seenKeysRef = useRef<Set<string>>(new Set())

  // 记录已经渲染过的条目：只有"本次挂载期间新出现"的流式条目才在首批文字上
  // 做 glyph reveal；首屏回放的历史文本永远保持纯文本。
  useEffect(() => {
    const seen = seenKeysRef.current
    for (const item of view.timeline) seen.add(`${item.kind}-${item.seq}`)
  }, [view.timeline])

  const seen = seenKeysRef.current
  const live = active && connected === true

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
      <ol className="relative mt-3 space-y-3">
        {view.timeline.map((item, index) => {
          const key = `${item.kind}-${item.seq}`
          // 思考块的"正在思考"微光只在它还是流尾时亮：后面一旦出现
          // 工具/正文/终答，说明这段思考已收口。
          const streaming = active && index === view.timeline.length - 1
          const appearedLive = live && seen.size > 0 && !seen.has(key)
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
                  <Markdown
                    text={item.text}
                    streaming={streaming}
                    animateAtMount={streaming && appearedLive}
                  />
                </li>
              )
            case "thinking":
              return (
                <li key={key}>
                  <ThinkingBlock
                    steps={item.steps}
                    active={streaming}
                    text={item.text}
                  />
                </li>
              )
            case "tasks":
              return (
                <li key={key}>
                  <TasksBlock items={item.items} />
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
      </ol>
    </div>
  )
}
