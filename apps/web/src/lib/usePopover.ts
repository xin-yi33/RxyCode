// 弹层（菜单/浮层）通用关闭行为：
// - Esc 关闭，但若顶层还有 <dialog open>（模态层更高）就让位 ——
//   Esc 一次只关最上层（PRD §10）。
// - 点击层外任意处关闭（mousedown 先于 click，避免选中文字误关）。
// 返回包住“触发器 + 弹层”的容器 ref。
import { useEffect, useRef, type RefObject } from "react"

export function usePopover<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  onClose: () => void,
): RefObject<T | null> {
  const ref = useRef<T | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      if (document.querySelector("dialog[open]")) return
      event.stopPropagation()
      onCloseRef.current()
    }
    const onDown = (event: MouseEvent) => {
      const root = ref.current
      if (root && event.target instanceof Node && !root.contains(event.target)) {
        onCloseRef.current()
      }
    }
    // document 层冒泡监听：stopPropagation 可挡住 window 级 Esc（控制台等），
    // 保证只关最上层弹层。
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onDown)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onDown)
    }
  }, [open])

  return ref
}
