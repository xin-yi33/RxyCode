export function BrowserPreview({
  proxyPath,
  unavailable,
}: {
  proxyPath: string
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
      <iframe title="preview" sandbox="allow-scripts" src={proxyPath} referrerPolicy="no-referrer" />
    </section>
  )
}
