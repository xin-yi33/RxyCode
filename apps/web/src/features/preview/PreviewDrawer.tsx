import { useEffect, useRef } from "react"

import { IconClose } from "../../components/icons"
import type { PreviewJob } from "../../sdk/client"

type PreviewDrawerProps = {
  job: PreviewJob | null
  title: string
  open: boolean
  onClose: () => void
}

// 预览抽屉：桌面 50/50 右分屏，移动端全屏覆盖（E3 §07 fig-39/40）。
// iframe 始终 sandbox + no-referrer —— 预览内容是不可信产物。
export function PreviewDrawer({ job, title, open, onClose }: PreviewDrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null
  const ready = job?.status === "ready" && job.preview_url
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`预览 ${title}`}
      data-preview-drawer
      className={
        "fixed inset-0 z-40 flex flex-col bg-card sm:inset-y-0 sm:right-0 " +
        "sm:left-auto sm:w-1/2 sm:border-l sm:border-border sm:shadow-xl"
      }
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="min-w-0 flex-1 truncate text-sm">{title}</span>
        {job?.status ? (
          <span className="text-xs text-muted">
            {job.status === "ready"
              ? "就绪"
              : job.status === "failed"
                ? "失败"
                : job.status === "expired" || job.status === "cancelled"
                  ? job.status
                  : "生成中…"}
          </span>
        ) : null}
        <button
          ref={closeRef}
          type="button"
          aria-label="关闭预览"
          className="rounded p-1.5 text-muted hover:bg-sidebar"
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
