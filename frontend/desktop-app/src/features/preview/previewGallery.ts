export type ArtifactKind = 'hero' | 'gallery' | 'video' | 'json'

export interface PreviewArtifact {
  kind: ArtifactKind
  path: string
  bytes: number
  durationSec?: number
}

export function canRender(artifact: PreviewArtifact): boolean {
  if (artifact.bytes > 25 * 1024 * 1024) return false
  if (artifact.kind === 'hero') return true
  if (artifact.kind === 'video') return (artifact.durationSec ?? 0) <= 8
  return true
}

export function normalizePreviewPath(path: string): string {
  return path.replace(/\\/g, '/')
}
