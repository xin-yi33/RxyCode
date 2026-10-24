import { IconCheck, IconClose, IconCopy } from "./icons"
import { useCopyFeedback, type CopyFeedbackState } from "../lib/useCopyFeedback"

type CopyButtonProps = {
  text: string | (() => string)
  /** Visible label; when set the button renders icon + text. */
  label?: string
  ariaLabel?: string
  className?: string
  size?: number
  /** Pass the parent's feedback hook to share one timer across buttons. */
  feedback?: ReturnType<typeof useCopyFeedback>
}

function stateLabel(state: CopyFeedbackState, fallback: string): string {
  if (state === "copied") return "已复制"
  if (state === "failed") return "复制失败"
  return fallback
}

/**
 * The one copy affordance of the web UI: 2.5s check + fade, fixed icon box so
 * switching icons never changes geometry, failure is visible instead of a fake
 * success, and the copy result always comes from the real clipboard helper.
 */
export function CopyButton({
  text,
  label,
  ariaLabel = "复制",
  className = "",
  size = 14,
  feedback,
}: CopyButtonProps) {
  const own = useCopyFeedback()
  const hook = feedback ?? own
  const { state, fading, copy } = hook
  const onClick = () => {
    const value = typeof text === "function" ? text() : text
    void copy(value)
  }
  const icon =
    state === "copied" ? (
      <IconCheck size={size} />
    ) : state === "failed" ? (
      <IconClose size={size} />
    ) : (
      <IconCopy size={size} />
    )
  return (
    <button
      type="button"
      data-testid="chat-copy-button"
      data-copy-state={state}
      data-copy-fading={fading ? "true" : "false"}
      onClick={onClick}
      aria-label={stateLabel(state, ariaLabel)}
      title={stateLabel(state, ariaLabel)}
      className={
        `inline-flex items-center justify-center gap-1 ${className} ` +
        (fading ? "opacity-0 transition-opacity duration-300" : "opacity-100")
      }
    >
      <span
        aria-hidden="true"
        className="inline-flex shrink-0 items-center justify-center"
        style={{ width: size + 2, height: size + 2 }}
      >
        {icon}
      </span>
      {label ? <span>{label}</span> : null}
    </button>
  )
}
