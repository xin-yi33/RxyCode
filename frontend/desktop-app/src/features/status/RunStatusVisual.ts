import { createElement, type ReactElement } from 'react'
import { fromSessionRunState, projectStatus, runningHighlight } from '../../lib/statusProjection.ts'

export function RunStatusVisual(props: { runState: string }): ReactElement {
  const backend = fromSessionRunState(props.runState)
  return createElement('span', {
    'data-testid': 'run-status-visual',
    'data-visual': projectStatus(backend),
    'data-highlight': runningHighlight(backend) ? 'true' : 'false'
  })
}
