// 原生 <dialog> + showModal() 模态层（PRD §10 弹层层级）：
// 顶层 top-layer 渲染自带焦点圈禁、Esc 关闭与 ::backdrop；关闭后焦点
// 自动回到触发元素。组件挂载即打开、卸载即关闭 —— 调用方用条件渲染控制，
// 每次打开都拿到全新表单状态（未保存的密钥随卸载丢弃）。
import { useEffect, useRef, type ReactNode } from "react"

import { cn } from "../../lib/cn"
import { Button } from "./button"

export function Modal({
  onClose,
  label,
  className,
  children,
}: {
  onClose: () => void
  label: string
  className?: string
  children?: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const el = ref.current
    if (!el || el.open) return
    try {
      el.showModal()
    } catch {
      // 旧环境兜底：无 showModal 时退化为普通浮层（不阻断功能）。
      el.setAttribute("open", "")
    }
  }, [])

  return (
    <dialog
      ref={ref}
      aria-label={label}
      className={cn(
        "m-auto max-h-[85vh] w-[calc(100vw-2rem)] max-w-md overflow-y-auto " +
          "rounded-xl border border-border bg-card p-0 text-foreground " +
          "shadow-xl backdrop:bg-black/50",
        className,
      )}
      // Esc（cancel）与程序化 close 都走这里，统一由父层卸载本组件。
      onClose={() => onCloseRef.current()}
      onClick={(event) => {
        const el = ref.current
        if (!el || event.target !== el) return
        // 点击落在 dialog 内容盒之外 = 点了 ::backdrop。
        const rect = el.getBoundingClientRect()
        const inside =
          event.clientX >= rect.left &&
          event.clientX <= rect.right &&
          event.clientY >= rect.top &&
          event.clientY <= rect.bottom
        if (!inside) onCloseRef.current()
      }}
    >
      {children}
    </dialog>
  )
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel = "确认",
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: {
  title: string
  body?: ReactNode
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <Modal onClose={onClose} label={title} className="max-w-sm">
      <div className="p-5">
        <h3 className="text-base font-semibold">{title}</h3>
        {body ? <div className="mt-2 text-sm text-muted">{body}</div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={busy}
            className={danger ? "bg-failure text-background" : undefined}
          >
            {busy ? "处理中…" : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
