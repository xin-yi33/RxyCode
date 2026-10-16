import { useState } from "react"

type HandoffWindow = Window & {
  rxyAuthorizeHandoff?: (sessionId: string) => boolean | Promise<boolean>
}

export function BrowserHandoff({
  sessionId,
  authorized,
  onAuthorize,
}: {
  sessionId: string
  authorized: boolean
  onAuthorize?: () => boolean | Promise<boolean>
}) {
  const [granted, setGranted] = useState(authorized)

  async function authorize() {
    try {
      if (onAuthorize) {
        if (!(await onAuthorize())) {
          return
        }
      }
      const bridge =
        typeof window !== "undefined" ? (window as HandoffWindow).rxyAuthorizeHandoff : undefined
      if (bridge) {
        if (!(await bridge(sessionId))) {
          return
        }
      }
      if (!onAuthorize && !bridge) {
        return
      }
      setGranted(true)
    } catch {
      return
    }
  }

  return (
    <section
      aria-label="browser-handoff"
      data-session={sessionId}
      data-authorized={granted ? "true" : "false"}
      data-profile-kind="agent"
    >
      {granted ? (
        <p data-state="continued">agent session continued</p>
      ) : (
        <button type="button" onClick={authorize}>
          授权接管
        </button>
      )}
      <p data-chrome="isolated">user Chrome data is not shared</p>
    </section>
  )
}
