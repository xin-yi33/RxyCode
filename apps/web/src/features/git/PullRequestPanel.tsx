export function PullRequestPanel({
  url,
  state,
  error,
}: {
  url?: string
  state?: string
  error?: string
}) {
  if (error) {
    return (
      <section aria-label="pull-request">
        <p>{error}</p>
      </section>
    )
  }
  return (
    <section aria-label="pull-request">
      <a href={url}>{url}</a>
      <p>{state}</p>
    </section>
  )
}
