import { useState } from "react"

import { Button } from "../../components/ui/button"
import { ApiError, createClient } from "../../sdk/client"
import type { TimelineItem } from "../runs/eventReducer"

const api = createClient()

type ApprovalItemData = Extract<TimelineItem, { kind: "approval" }>

const RESOLVED_TEXT: Record<string, string> = {
  approved: "已批准",
  rejected: "已拒绝",
  expired: "已过期",
  cancelled: "已取消",
}

// F5 审批卡：标题 + 工具/命令/描述/工作目录 + 批准/拒绝。
// 提交前先 GET 最新 revision 再 POST；409 拉取确认是否已被别处处理。
export function ApprovalItem({
  runId,
  item,
}: {
  runId: string
  item: ApprovalItemData
}) {
  const [submitting, setSubmitting] = useState<"approved" | "rejected" | null>(null)
  const [error, setError] = useState("")
  // 本地乐观态：POST 成功后直接折叠（不等 SSE）；409 确认已处理时标记。
  const [localStatus, setLocalStatus] = useState<string | null>(null)

  const status = localStatus ?? item.status
  if (status !== "pending") {
    return (
      <p
        data-approval-id={item.approvalId}
        className="text-xs text-muted"
      >
        {item.tool ? `${item.tool} · ` : ""}
        {RESOLVED_TEXT[status] ?? "已被处理"}
      </p>
    )
  }

  const decide = async (decision: "approved" | "rejected") => {
    if (submitting) return
    setSubmitting(decision)
    setError("")
    try {
      // 先取最新 revision 再裁决 —— 手里的 revision 可能已经过期。
      const list = await api.listApprovals(runId)
      const current = list.approvals.find(
        (row) => row.approval_id === item.approvalId,
      )
      if (!current) {
        // 已不在待办里 —— 被别处处理了。
        setLocalStatus("resolved")
        return
      }
      await api.decideApproval(runId, {
        approval_id: item.approvalId,
        decision,
        revision: current.revision,
      })
      setLocalStatus(decision)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // APPROVAL_STALE —— 重新拉一次确认是否已经处理。
        try {
          const again = await api.listApprovals(runId)
          const still = again.approvals.some(
            (row) => row.approval_id === item.approvalId,
          )
          if (still) {
            setError("审批状态已变化，请重试")
          } else {
            setLocalStatus("resolved")
          }
        } catch {
          setError("提交失败，可重试")
        }
      } else {
        setError("提交失败，可重试")
      }
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <article
      data-approval-id={item.approvalId}
      className="rounded-lg border border-waiting/40 bg-card p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">需要你批准</p>
        <span className="rounded-full bg-waiting/15 px-2 py-0.5 text-xs text-waiting-ink">
          等待审批
        </span>
      </div>
      <dl className="mt-2 space-y-1 text-xs">
        <div className="flex gap-2">
          <dt className="w-16 shrink-0 text-muted">工具</dt>
          <dd className="font-mono">{item.tool || "—"}</dd>
        </div>
        {item.command ? (
          <div className="flex gap-2">
            <dt className="w-16 shrink-0 text-muted">命令</dt>
            <dd className="min-w-0">
              <code className="block overflow-x-auto whitespace-nowrap rounded bg-sidebar px-1.5 py-1 font-mono">
                {item.command}
              </code>
            </dd>
          </div>
        ) : null}
        {item.description ? (
          <div className="flex gap-2">
            <dt className="w-16 shrink-0 text-muted">说明</dt>
            <dd className="min-w-0 break-words">{item.description}</dd>
          </div>
        ) : null}
        {item.workdir ? (
          <div className="flex gap-2">
            <dt className="w-16 shrink-0 text-muted">目录</dt>
            <dd className="min-w-0 break-all font-mono">{item.workdir}</dd>
          </div>
        ) : null}
      </dl>
      {/* 审批中立（设计规范 §07）：批准/拒绝同用次级按钮，不做视觉引导。 */}
      <div className="mt-3 flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={submitting !== null}
          onClick={() => void decide("approved")}
        >
          {submitting === "approved" ? "提交中…" : "批准"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={submitting !== null}
          onClick={() => void decide("rejected")}
        >
          {submitting === "rejected" ? "提交中…" : "拒绝"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-failure">
          {error}
        </p>
      ) : null}
    </article>
  )
}
