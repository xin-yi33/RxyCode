import { useState } from "react"

type HandoffWindow = Window & {
  rxyAuthorizeHandoff?: (sessionId: string) => void | Promise<void>
}

export function BrowserHandoff({
  sessionId,
  authorized,
  onAuthorize,
}: {
  sessionId: string
  authorized: boolean
  onAuthorize?: () => void
}) {
  const [granted, setGranted] = useState(authorized)

  async function authorize() {
    let accepted = false
    if (onAuthorize) {
      onAuthorize()
      accepted = true
    }
    if (typeof window !== "undefined") {
      const bridge = (window as HandoffWindow).rxyAuthorizeHandoff
      if (bridge) {
        await bridge(sessionId)
        accepted = true
      }
    }
    if (accepted) {
      setGranted(true)
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
