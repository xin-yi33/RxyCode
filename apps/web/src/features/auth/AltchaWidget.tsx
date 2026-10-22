import { useEffect, useRef, useState } from "react"
import { AltchaCompatError, solveAltchaCompat, type AltchaCompatCode } from "./altchaCompat"
import {
  currentClientPrefersMainThreadAltcha,
  isAuthTransportAllowed,
} from "./authTransport"

type AltchaState = { state?: string; payload?: string }
type CompatView = "widget" | "solving" | "verified" | "failed" | "expired"

/**
 * ALTCHA proof-of-work widget — solves a server-signed challenge in the
 * background (auto=onload), then hands the verifiable payload to the parent
 * for the next auth POST. Deliberately unstyled-small; the PoW does the work,
 * not a puzzle UI.
 */
export function AltchaWidget({ onVerify }: { onVerify: (payload: string) => void }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<HTMLElement | null>(null)
  const onVerifyRef = useRef(onVerify)
  const runCompatRef = useRef<(() => void) | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const generationRef = useRef(0)
  const expiryTimerRef = useRef<number | null>(null)
  const compatStartedRef = useRef(false)
  const [preferMainThread] = useState(currentClientPrefersMainThreadAltcha)
  const [widgetReady, setWidgetReady] = useState(false)
  const [compatView, setCompatView] = useState<CompatView>("widget")
  const [compatCode, setCompatCode] = useState<AltchaCompatCode | null>(null)

  onVerifyRef.current = onVerify

  useEffect(() => {
    let alive = true
    let widgetStateHandler: ((event: Event) => void) | null = null

    const clearExpiry = () => {
      if (expiryTimerRef.current !== null) {
        window.clearTimeout(expiryTimerRef.current)
        expiryTimerRef.current = null
      }
    }

    const startCompat = () => {
      if (!alive) return
      const generation = ++generationRef.current
      controllerRef.current?.abort()
      controllerRef.current = new AbortController()
      clearExpiry()
      onVerifyRef.current("")
      setCompatCode(null)
      setCompatView("solving")

      const controller = controllerRef.current
      if (!controller) return
      void solveAltchaCompat(controller.signal).then(
        ({ payload, expiresAt }) => {
          if (!alive || generationRef.current !== generation) return
          controllerRef.current = null
          onVerifyRef.current(payload)
          setCompatView("verified")
          expiryTimerRef.current = window.setTimeout(() => {
            if (!alive || generationRef.current !== generation) return
            expiryTimerRef.current = null
            onVerifyRef.current("")
            setCompatView("expired")
          }, Math.max(0, expiresAt - Date.now()))
        },
        (error: unknown) => {
          if (!alive || generationRef.current !== generation) return
          controllerRef.current = null
          onVerifyRef.current("")
          if (error instanceof DOMException && error.name === "AbortError") return
          const code = error instanceof AltchaCompatError ? error.code : "COMPUTE"
          setCompatCode(code)
          setCompatView("failed")
        },
      )
    }

    runCompatRef.current = startCompat

    const onState = (event: Event) => {
      const detail = (event as CustomEvent<AltchaState>).detail
      if (compatStartedRef.current) return
      if (detail?.state === "verified" && detail.payload) {
        onVerifyRef.current(detail.payload)
      } else if (detail?.state === "error") {
        compatStartedRef.current = true
        onVerifyRef.current("")
        startCompat()
      } else {
        // The PoW token is single-use and must not survive a reset, expiry,
        // retry, or any other transition away from the verified state.
        onVerifyRef.current("")
      }
    }

    if (!isAuthTransportAllowed(window.location)) {
      onVerifyRef.current("")
      setCompatCode("INSECURE_CONTEXT")
      setCompatView("failed")
    } else if (preferMainThread) {
      // Mobile devices use the same V1 challenge directly in chunked JS. This
      // is a performance/compatibility choice, never an authorization rule.
      compatStartedRef.current = true
      startCompat()
    } else {
      // Keep the worker-backed official element out of the initial/mobile
      // bundle, and attach the listener before connecting the custom element.
      void import("altcha").then(
        () => {
          if (!alive || !hostRef.current) return
          const el = document.createElement("altcha-widget")
          el.setAttribute("challenge", "/api/v1/auth/altcha")
          el.setAttribute("auto", "onload")
          el.setAttribute("configuration", '{"hideFooter":true,"hideLogo":true}')
          el.style.setProperty("--altcha-max-width", "100%")
          el.addEventListener("statechange", onState)
          widgetStateHandler = onState
          widgetRef.current = el
          hostRef.current.appendChild(el)
          setWidgetReady(true)
        },
        () => {
          if (!alive) return
          compatStartedRef.current = true
          startCompat()
        },
      )
    }

    return () => {
      alive = false
      generationRef.current += 1
      controllerRef.current?.abort()
      controllerRef.current = null
      clearExpiry()
      runCompatRef.current = null
      onVerifyRef.current("")
      if (widgetRef.current && widgetStateHandler) {
        widgetRef.current.removeEventListener("statechange", widgetStateHandler)
      }
      widgetRef.current?.remove()
      widgetRef.current = null
    }
  }, [preferMainThread])

  if (preferMainThread || compatView !== "widget") {
    const message =
      compatView === "widget" || compatView === "solving"
        ? "正在进行兼容验证…"
        : compatView === "verified"
          ? "验证通过"
          : compatView === "expired"
            ? "验证已过期，请重新验证"
            : compatCode === "INSECURE_CONTEXT"
              ? "验证码需要 HTTPS 安全入口；HTTP 下不会发送凭据或验证码。请改用 https://rxycode.xyz，或在本机使用 localhost。"
              : `兼容验证失败（${compatCode ?? "COMPUTE"}）`

    return (
      <div className="space-y-2 text-sm" aria-live="polite">
        <p role={compatView === "failed" ? "alert" : "status"}>{message}</p>
        {(compatView === "failed" || compatView === "expired") && (
          <button
            type="button"
            className="rounded border px-3 py-1 text-sm"
            onClick={() => {
              compatStartedRef.current = true
              runCompatRef.current?.()
            }}
          >
            重试验证
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2 text-sm" aria-live="polite">
      <div ref={hostRef} />
      {!widgetReady ? <p role="status">正在加载安全验证组件…</p> : null}
    </div>
  )
}
