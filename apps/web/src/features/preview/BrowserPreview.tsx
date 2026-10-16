export function BrowserPreview({
  proxyPath,
  html,
  unavailable,
}: {
  proxyPath: string
  html?: string
  unavailable?: boolean
}) {
  const allowed = proxyPath.startsWith("/api/v1/previews/")
  if (unavailable || !allowed) {
    return (
      <section aria-label="preview">
        <p>target unavailable</p>
      </section>
    )
  }
  return (
    <section aria-label="preview">
      <iframe title="preview" sandbox="" src={proxyPath} srcDoc={html} referrerPolicy="no-referrer" />
    </section>
  )
}
