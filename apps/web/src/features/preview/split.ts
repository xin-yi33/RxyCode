// UI-08/09: preview split state, drag math and spring presets.
//
// The drag path is direct-follow (ratio comes straight from the pointer).
// Only two deliberate transitions animate, each with a real caller:
//   - rigid   -> reset to 50/50 (double-click on the handle, "重置分栏" button)
//   - confirm -> small adjustments (keyboard nudge, 1% snap on drop)
// Keeping both presets here (instead of inline numbers at the call sites)
// means `SPRING` has no dead entries: grep shows both consumers.

export type SplitState = {
  leftRatio: number
  previewOpen: boolean
}

export type SpringConfig = {
  stiffness: number
  damping: number
  mass: number
}

export const SPRING = {
  rigid: { stiffness: 1200, damping: 80, mass: 1 },
  confirm: { stiffness: 380, damping: 18, mass: 1 },
} as const

export const DEFAULT_LEFT_RATIO = 0.5
export const MIN_LEFT_RATIO = 0.2
// A left pane strictly wider than this ratio collapses the preview back into
// the chat column. The threshold is a ratio of the content workspace width.
export const COLLAPSE_LEFT_RATIO = 0.82
export const SNAP_LEFT_RATIO = 0.5
export const SNAP_TOLERANCE = 0.01
export const KEYBOARD_STEP = 0.02

export function clampLeftRatio(ratio: number): number {
  if (!Number.isFinite(ratio)) return DEFAULT_LEFT_RATIO
  return Math.min(COLLAPSE_LEFT_RATIO, Math.max(MIN_LEFT_RATIO, ratio))
}

export function shouldCollapsePreview(ratio: number): boolean {
  return ratio > COLLAPSE_LEFT_RATIO
}

// Pointer position -> left ratio. The workspace (not the pane) width is the
// denominator so the divider tracks the cursor exactly.
export function ratioFromPointerX(
  clientX: number,
  rect: { left: number; width: number },
): number {
  if (!Number.isFinite(rect.width) || rect.width <= 0) return DEFAULT_LEFT_RATIO
  return (clientX - rect.left) / rect.width
}

export function ratioPercent(ratio: number): number {
  return Math.round(clampLeftRatio(ratio) * 100)
}

/** Reduced-motion preference from the appearance engine or the OS. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false
  if (document.documentElement.classList.contains("reduced-motion")) return true
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

export type SpringHandle = {
  cancel: () => void
}

export type SpringRunOptions = {
  config: SpringConfig
  from: number
  to: number
  onUpdate: (value: number) => void
  onSettled?: () => void
  reducedMotion?: boolean
}

const REST_DISTANCE = 0.0005
const REST_VELOCITY = 0.005

// Real rAF spring integrator (semi-implicit Euler, clamped dt). Callers pass
// one of the SPRING presets; returning a cancel handle lets pointerdown,
// unmount and Esc abort an in-flight animation cleanly.
export function runSpring(options: SpringRunOptions): SpringHandle {
  const { config, from, to, onUpdate, onSettled, reducedMotion } = options
  if (reducedMotion || from === to) {
    onUpdate(to)
    onSettled?.()
    return { cancel: () => undefined }
  }
  let frame = 0
  let value = from
  let velocity = 0
  let last = performance.now()
  let cancelled = false
  const step = (now: number) => {
    if (cancelled) return
    // Backgrounded tabs deliver huge deltas; clamp so the integration stays stable.
    const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000))
    last = now
    const acceleration =
      (-config.stiffness * (value - to) - config.damping * velocity) / config.mass
    velocity += acceleration * dt
    value += velocity * dt
    if (
      Math.abs(value - to) <= REST_DISTANCE &&
      Math.abs(velocity) <= REST_VELOCITY
    ) {
      onUpdate(to)
      onSettled?.()
      return
    }
    onUpdate(value)
    frame = window.requestAnimationFrame(step)
  }
  frame = window.requestAnimationFrame(step)
  return {
    cancel: () => {
      cancelled = true
      if (frame !== 0) window.cancelAnimationFrame(frame)
    },
  }
}
