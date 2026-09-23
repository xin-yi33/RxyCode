import { createElement, type ReactElement } from 'react'
import { galleryVisualState } from './galleryVisualState.ts'
import {
  artifactView,
  canRender,
  cacheKey,
  type PreviewArtifact
} from './previewArtifacts.ts'

export function PreviewGallery({
  artifacts,
  loading = false,
  error = null,
  narrow = false,
  dark = true
}: {
  artifacts: PreviewArtifact[]
  loading?: boolean
  error?: string | null
  narrow?: boolean
  dark?: boolean
}): ReactElement {
  const visual = galleryVisualState({ artifacts, loading, error, narrow, dark })
  const visible = artifacts.filter(canRender)
  const children: ReactElement[] = []
  if (visual === 'loading') {
    children.push(createElement('p', { key: 'loading', 'data-testid': 'gallery-loading' }, 'loading'))
  } else if (visual === 'error') {
    children.push(createElement('p', { key: 'error', 'data-testid': 'gallery-error' }, error))
  } else if (visual === 'empty') {
    children.push(createElement('p', { key: 'empty', 'data-testid': 'gallery-empty' }, 'empty'))
  }
  for (const artifact of visible) {
    const view = artifactView(artifact)
    const key = cacheKey(artifact)
    if (view.tag === 'img') {
      children.push(
        createElement('img', {
          key,
          src: view.src,
          alt: '',
          'data-kind': view.kind,
          'data-cache-key': key,
          style: view.maxWidth !== undefined ? { maxWidth: view.maxWidth } : undefined
        })
      )
    } else if (view.tag === 'video') {
      children.push(
        createElement('video', {
          key,
          src: view.src,
          controls: true,
          'data-kind': view.kind,
          'data-cache-key': key
        })
      )
    } else {
      children.push(
        createElement(
          'pre',
          { key, 'data-kind': view.kind, 'data-cache-key': key, 'data-path': artifact.path },
          view.jsonText
        )
      )
    }
  }
  return createElement(
    'div',
    { 'data-gallery': 'cli-anything', 'data-visual-state': visual, 'data-phase-i': 'false' },
    children
  )
}
