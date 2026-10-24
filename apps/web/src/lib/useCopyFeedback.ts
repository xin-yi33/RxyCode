import { useCallback, useEffect, useRef, useState } from "react"

import { copyText } from "./clipboard"

export type CopyFeedbackState = "idle" | "copied" | "failed"

export type CopyFeedbackOptions = {
  /** How long the success state is held before it starts fading. */
  holdMs?: number
  /** How long the fade-out lasts before returning to idle. */
  fadeMs?: number
}

export type CopyFeedback = {
  state: CopyFeedbackState
  /** True during the fade-out window (success icon still rendered, fading). */
  fading: boolean
  copy: (text: string) => Promise<boolean>
  reset: () => void
}

function clearTimer(ref: { current: number | null }) {
  if (ref.current !== null) {
    window.clearTimeout(ref.current)
    ref.current = null
  }
}

/**
 * Copy feedback shared by every copy affordance (code blocks, console, chat).
 *
 * Contract: a successful copy shows the check for holdMs (2500ms by default),
 * then fades for fadeMs (300ms) and returns to idle. A second successful copy
 * restarts the whole cycle, so an earlier timer can never clear a newer
 * feedback. A failed copy shows the failure state (no fake success). Timers are
 * always cleaned up on unmount or reset.
 */
export function useCopyFeedback(options: CopyFeedbackOptions = {}): CopyFeedback {
  const holdMs = options.holdMs ?? 2500
  const fadeMs = options.fadeMs ?? 300
  const [state, setState] = useState<CopyFeedbackState>("idle")
  const [fading, setFading] = useState(false)
  const holdTimer = useRef<number | null>(null)
  const fadeTimer = useRef<number | null>(null)
  const mounted = useRef(true)

  const reset = useCallback(() => {
    clearTimer(holdTimer)
    clearTimer(fadeTimer)
    if (mounted.current) {
      setFading(false)
      setState("idle")
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      clearTimer(holdTimer)
      clearTimer(fadeTimer)
    }
  }, [])

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      clearTimer(holdTimer)
      clearTimer(fadeTimer)
      if (mounted.current) setFading(false)
      const ok = await copyText(text)
      if (!mounted.current) return ok
      if (!ok) {
        setState("failed")
        holdTimer.current = window.setTimeout(() => {
          if (mounted.current) setState("idle")
        }, holdMs)
        return false
      }
      setState("copied")
      holdTimer.current = window.setTimeout(() => {
        if (!mounted.current) return
        setFading(true)
        fadeTimer.current = window.setTimeout(() => {
          if (!mounted.current) return
          setFading(false)
          setState("idle")
        }, fadeMs)
      }, holdMs)
      return true
    },
    [fadeMs, holdMs],
  )

  return { state, fading, copy, reset }
}
