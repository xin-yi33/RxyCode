export function BrowserHandoff({
  sessionId,
  authorized,
}: {
  sessionId: string
  authorized: boolean
}) {
  return (
    <section
      aria-label="browser-handoff"
      data-session={sessionId}
      data-authorized={authorized ? "true" : "false"}
      data-profile-kind="agent"
    >
      {authorized ? (
        <p data-state="continued">agent session continued</p>
      ) : (
        <button type="button">授权接管</button>
      )}
      <p data-chrome="isolated">user Chrome data is not shared</p>
    </section>
  )
}
