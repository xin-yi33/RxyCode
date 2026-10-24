import { useState } from "react"

import { Collapse } from "../../components/Collapse"
import {
  IconChevronDown,
  IconCheck,
  IconClose,
  IconSpinner,
} from "../../components/icons"
import type { TaskEntry } from "../runs/eventReducer"

// 「任务清单」块：plan.updated/todo.updated 合并出的实时待办列表。
// 默认展开——长任务必须看得见进度；点击标题可收起（共享 Collapse）。
function statusIcon(status: string) {
  switch (status) {
    case "completed":
    case "done":
      return <IconCheck size={13} className="shrink-0 text-success-ink" />
    case "in_progress":
    case "running":
      return <IconSpinner size={13} className="shrink-0 text-running-ink" />
    case "cancelled":
    case "blocked":
    case "failed":
      return <IconClose size={13} className="shrink-0 text-failure-ink" />
    default:
      return (
        <span className="h-3 w-3 shrink-0 rounded-full border border-muted-ink" />
      )
  }
}

export function TasksBlock({ items }: { items: TaskEntry[] }) {
  const [open, setOpen] = useState(true)
  const done = items.filter(
    (item) => item.status === "completed" || item.status === "done",
  ).length
  return (
    <div
      data-tasks
      className="rounded-lg border border-border bg-card text-xs"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted"
      >
        <span>任务清单</span>
        <span className="text-muted-ink">
          （{done}/{items.length}）
        </span>
        <IconChevronDown
          size={12}
          className={
            "ml-auto shrink-0 transition-transform " + (open ? "rotate-180" : "")
          }
        />
      </button>
      <Collapse open={open}>
        <ul className="space-y-1 border-t border-border px-3 py-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-2">
              <span className="mt-0.5">{statusIcon(item.status)}</span>
              <span
                className={
                  "min-w-0 break-words text-foreground " +
                  (item.status === "completed" || item.status === "done"
                    ? "text-muted-ink line-through"
                    : item.status === "cancelled"
                      ? "text-muted-ink line-through"
                      : "")
                }
              >
                {item.title || item.id}
              </span>
            </li>
          ))}
        </ul>
      </Collapse>
    </div>
  )
}
