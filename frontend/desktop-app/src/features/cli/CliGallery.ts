import { createElement, type ReactElement } from 'react'
import { PreviewGallery } from '../preview/previewGallery.ts'
import type { PreviewArtifact } from '../preview/previewArtifacts.ts'

export function CliGallery(props: {
  blocked: boolean
  missing: readonly string[]
  artifacts: readonly PreviewArtifact[]
}): ReactElement {
  return createElement(
    'section',
    { 'data-testid': 'cli-gallery' },
    props.blocked
      ? createElement('p', { 'data-testid': 'cli-blocked' }, `BLOCKED_PREREQUISITE: ${props.missing.join(', ')}`)
      : null,
    createElement(PreviewGallery, { artifacts: [...props.artifacts] })
  )
}
