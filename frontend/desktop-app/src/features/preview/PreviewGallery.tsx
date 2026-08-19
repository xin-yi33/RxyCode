import { canRender, type PreviewArtifact } from './previewGallery.ts'

export function PreviewGallery({ artifacts }: { artifacts: PreviewArtifact[] }): React.JSX.Element {
  return (
    <div data-gallery="cli-anything">
      {artifacts.filter(canRender).map((artifact) => (
        <div key={artifact.path} data-kind={artifact.kind} />
      ))}
    </div>
  )
}
