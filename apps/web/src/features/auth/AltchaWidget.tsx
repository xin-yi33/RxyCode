import { useEffect, useRef } from "react"
import "altcha"

declare global {
  namespace React {
    namespace JSX {
      interface IntrinsicElements {
        "altcha-widget": Record<string, unknown> & {
          ref?: React.Ref<HTMLElement>
        }
      }
    }
  }
}

type AltchaState = { state?: string; payload?: string }

/**
 * ALTCHA proof-of-work widget — solves a server-signed challenge in the
 * background (auto=onload), then hands the verifiable payload to the parent
 * for the next auth POST. Deliberately unstyled-small; the PoW does the work,
 * not a puzzle UI.
 */
export function AltchaWidget({ onVerify }: { onVerify: (payload: string) => void }) {
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onState = (event: Event) => {
      const detail = (event as CustomEvent<AltchaState>).detail
      if (detail?.state === "verified" && detail.payload) {
        onVerify(detail.payload)
      } else {
        // The PoW token is single-use and must not survive a reset, expiry,
        // retry, or any other transition away from the verified state.
        onVerify("")
      }
    }
    el.addEventListener("statechange", onState)
    return () => el.removeEventListener("statechange", onState)
  }, [onVerify])

  return (
    <altcha-widget
      ref={ref}
      challenge="/api/v1/auth/altcha"
      auto="onload"
      configuration='{"hideFooter":true,"hideLogo":true}'
      style={{ "--altcha-max-width": "100%" }}
    />
  )
}
