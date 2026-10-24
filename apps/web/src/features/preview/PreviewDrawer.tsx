import { useEffect, useRef } from "react"

import { FileName } from "../../components/FileName"
import { IconClose, IconRefresh } from "../../components/icons"
import type { PreviewJob } from "../../sdk/client"
import { usePreviewPane } from "./SplitWorkspace"

type PreviewDrawerProps = {
  job: PreviewJob | null
  title: string
  open?: boolean
  onClose: () => void
}

// 预览面（E3 §07 fig-39/40）：桌面是分屏右栏（Pane），手机是全屏覆盖层。
// iframe 始终 sandbox + no-referrer —— 预览内容是不可信产物。
// Esc 由 SplitWorkspace 统一处理：先恢复拖拽前快照，再考虑关闭预览。
export function PreviewDrawer({ job, title, open = true, onClose }: PreviewDrawerProps) {
  const pane = usePreviewPane()
  const mode = pane?.mode ?? "overlay"
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
  }, [open])

  if (!open) return null
  const ready = job?.status === "ready" && job.preview_url
  return (
    <div
      role="dialog"
      aria-modal={mode === "overlay" ? true : undefined}
      aria-label={`预览 ${title}`}
      data-preview-drawer
      data-preview-mode={mode}
      className={
        mode === "overlay"
          ? "fixed inset-0 z-40 flex flex-col bg-card"
          : "flex h-full min-h-0 w-full flex-col bg-card"
      }
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="min-w-0 flex-1 text-sm">
          <FileName name={title} />
        </span>
        {job?.status ? (
          <span className="shrink-0 text-xs text-muted">
            {job.status === "ready"
              ? "就绪"
              : job.status === "failed"
                ? "失败"
                : job.status === "expired" || job.status === "cancelled"
                  ? job.status
                  : "生成中…"}
          </span>
        ) : null}
        {pane && mode === "pane" ? (
          <button
            type="button"
            aria-label="重置分栏"
            title="恢复 50/50 分栏"
            className="shrink-0 rounded p-1.5 text-muted hover:bg-sidebar"
            onClick={() => pane.resetSplit()}
          >
            <IconRefresh size={14} />
          </button>
        ) : null}
        <button
          ref={closeRef}
          type="button"
          aria-label="关闭预览"
          className="shrink-0 rounded p-1.5 text-muted hover:bg-sidebar"
          onClick={onClose}
        >
          <IconClose size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {ready ? (
          <iframe
            src={job.preview_url ?? undefined}
            title={`预览 ${title}`}
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            className="h-full w-full border-0 bg-white"
          />
        ) : job?.status === "failed" || job?.status === "expired" ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
            <p className="text-sm text-failure">预览不可用</p>
            <p className="max-w-sm text-xs text-muted">
              {job.reason || job.error_code || "转换失败"}
            </p>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted">
            正在生成预览…
          </div>
        )}
      </div>
    </div>
  )
}
