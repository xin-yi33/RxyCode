import type { PreviewArtifact } from './previewGallery.ts'

export type GalleryVisualState = 'empty' | 'loading' | 'error' | 'narrow' | 'dark' | 'ok'

export function galleryVisualState(input: {
  artifacts: readonly PreviewArtifact[]
  loading: boolean
  error: string | null
  narrow: boolean
  dark: boolean
}): GalleryVisualState {
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.artifacts.length === 0) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
