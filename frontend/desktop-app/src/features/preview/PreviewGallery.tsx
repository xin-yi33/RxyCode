import { galleryVisualState } from './galleryVisualState.ts'
import { canRender, type PreviewArtifact } from './previewGallery.ts'

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
}): React.JSX.Element {
  const visual = galleryVisualState({ artifacts, loading, error, narrow, dark })
  const visible = artifacts.filter(canRender)
  return (
    <div data-gallery="cli-anything" data-visual-state={visual} data-phase-i="false">
      {visual === 'loading' ? <p data-testid="gallery-loading">loading</p> : null}
      {visual === 'error' ? <p data-testid="gallery-error">{error}</p> : null}
      {visual === 'empty' ? <p data-testid="gallery-empty">empty</p> : null}
      {visible.map((artifact) => (
        <div key={artifact.path} data-kind={artifact.kind} />
      ))}
    </div>
  )
}
