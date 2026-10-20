// W9-F3: run status -> 中文 chip text. Reused by the sidebar, the session
// page, and the F4 timeline/console work.
export const RUN_STATUS_TEXT: Record<string, string> = {
  pending: "排队中",
  leased: "运行中",
  running: "运行中",
  waiting_approval: "等待你的操作",
  cancel_requested: "取消中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  recovery_required: "需要恢复",
}

export const ACTIVE_RUN_STATUSES = new Set([
  "pending",
  "leased",
  "running",
  "waiting_approval",
  "cancel_requested",
  "recovery_required",
])

export function runStatusText(status: string): string {
  return RUN_STATUS_TEXT[status] ?? status
}

export function isActiveRunStatus(status: string): boolean {
  return ACTIVE_RUN_STATUSES.has(status)
}

export type StatusKind = "running" | "waiting" | "success" | "failure" | "idle"

export function runStatusKind(status: string): StatusKind {
  if (status === "waiting_approval" || status === "recovery_required") return "waiting"
  if (status === "succeeded") return "success"
  if (status === "failed" || status === "cancelled") return "failure"
  if (status === "leased" || status === "running" || status === "cancel_requested") {
    return "running"
  }
  return "idle"
}
