import { projectStatus, runningHighlight, type BackendRun } from '../lib/statusProjection.ts'

export function StatusIndicator({
  backend,
  visualState = 'ok'
}: {
  backend: BackendRun
  visualState?: 'empty' | 'loading' | 'error' | 'narrow' | 'dark' | 'ok'
}): React.JSX.Element {
  const visual = projectStatus(backend)
  const highlight = runningHighlight(backend)
  return (
    <span
      className={`status-indicator${highlight ? ' is-running' : ''}`}
      data-status={visual}
      data-visual-state={visualState}
      aria-label={visual}
    />
  )
}
