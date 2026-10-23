export function TestResults({
  exitCode,
  framework,
  summary,
}: {
  exitCode: number
  framework: string
  summary: string
}) {
  const failed = exitCode !== 0
  return (
    <section aria-label="test-results" data-status={failed ? "failed" : "passed"}>
      <p>{failed ? `${framework} failed` : `${framework} passed`}</p>
      <pre>{summary}</pre>
    </section>
  )
}
