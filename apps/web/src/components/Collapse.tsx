import type { ReactNode } from "react"

/**
 * Shared 0fr/1fr collapse (ThinkingBlock / TasksBlock / ToolRow).
 *
 * The content is ALWAYS mounted so streaming text/tool details never lose
 * state while closed; the closed row is 0fr + overflow hidden so it consumes no
 * space (and no residual padding). Reversing mid-transition is handled by CSS
 * grid interpolation, and closed content is made non-focusable with `inert`.
 */
export function Collapse({
  open,
  children,
  className = "",
  innerClassName = "",
  id,
}: {
  open: boolean
  children: ReactNode
  className?: string
  innerClassName?: string
  id?: string
}) {
  return (
    <div className={`rxy-collapse ${className}`} data-open={open ? "true" : "false"} id={id}>
      <div
        className={`rxy-collapse-inner ${innerClassName}`}
        inert={!open}
        aria-hidden={open ? undefined : true}
      >
        {children}
      </div>
    </div>
  )
}
