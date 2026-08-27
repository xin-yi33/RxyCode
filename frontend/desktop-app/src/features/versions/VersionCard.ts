import { createElement, type ReactElement } from 'react'
import type { VersionCardModel } from './version.timeline.ts'

export function VersionCard(props: {
  card: VersionCardModel
  rewindEnabled: boolean
  onDiff: (turnId: string) => void
  onRewind: (turnId: string) => void
}): ReactElement {
  return createElement(
    'article',
    { className: 'version-card', 'data-testid': `version-${props.card.version}` },
    createElement('h3', null, `v${props.card.version}`),
    createElement('p', null, props.card.summary),
    createElement('button', { type: 'button', onClick: () => props.onDiff(props.card.turnId) }, 'Diff'),
    createElement(
      'button',
      { type: 'button', disabled: !props.rewindEnabled, onClick: () => props.onRewind(props.card.turnId) },
      props.rewindEnabled ? 'Rewind' : 'Rewind (GX4 blocked)'
    )
  )
}
