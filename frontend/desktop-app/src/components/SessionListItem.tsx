import { chevron } from '../lib/sessionCategories.ts'
import { StatusIndicator } from './StatusIndicator.tsx'
import type { BackendRun } from '../lib/statusProjection.ts'

export function SessionListItem({
  title,
  expanded,
  backend
}: {
  title: string
  expanded: boolean
  backend: BackendRun
}): React.JSX.Element {
  return (
    <div className="session-item">
      <span style={{ marginRight: 4 }}>{chevron(expanded)}</span>
      {title}
      <StatusIndicator backend={backend} />
    </div>
  )
}
