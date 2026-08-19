import { projectStatus, type BackendRun } from '../lib/statusProjection.ts'

export function StatusIndicator({ backend }: { backend: BackendRun }): React.JSX.Element {
  const visual = projectStatus(backend)
  return <span data-status={visual} aria-label={visual} />
}
