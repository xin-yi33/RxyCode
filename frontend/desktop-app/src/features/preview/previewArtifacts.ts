export type ArtifactKind = 'hero' | 'gallery' | 'video' | 'json'

export interface PreviewSummary {
  headline?: string
  facts?: string[]
  warnings?: string[]
  next_actions?: string[]
}

export interface PreviewArtifact {
  kind: ArtifactKind
  path: string
  bytes: number
  durationSec?: number
  summary?: PreviewSummary
}

export const PREVIEW_HERO_MAX_PX = 1280
export const PREVIEW_BUDGET_BYTES = 25 * 1024 * 1024

export function canRender(artifact: PreviewArtifact): boolean {
  if (artifact.bytes > PREVIEW_BUDGET_BYTES) return false
  if (artifact.kind === 'hero') return true
  if (artifact.kind === 'video') return (artifact.durationSec ?? 0) <= 8
  return true
}

export function normalizePreviewPath(path: string): string {
  return path.replace(/\\/g, '/')
}

export function toFileUrl(path: string): string {
  const normalized = normalizePreviewPath(path)
  if (normalized.startsWith('file:')) return normalized
  if (/^[A-Za-z]:\//.test(normalized)) return `file:///${normalized}`
  if (normalized.startsWith('/')) return `file://${normalized}`
  return `file://${normalized}`
}

export function cacheKey(artifact: PreviewArtifact): string {
  return `${normalizePreviewPath(artifact.path)}:${artifact.bytes}`
}

export function artifactView(artifact: PreviewArtifact): {
  tag: 'img' | 'video' | 'pre'
  kind: ArtifactKind
  src: string
  maxWidth?: number
  jsonText?: string
} {
  const src = toFileUrl(artifact.path)
  if (artifact.kind === 'hero') return { tag: 'img', kind: 'hero', src, maxWidth: PREVIEW_HERO_MAX_PX }
  if (artifact.kind === 'gallery') return { tag: 'img', kind: 'gallery', src }
  if (artifact.kind === 'video') return { tag: 'video', kind: 'video', src }
  const summary = artifact.summary
  const jsonText =
    summary === undefined
      ? artifact.path
      : JSON.stringify({
          headline: summary.headline,
          facts: summary.facts,
          warnings: summary.warnings,
          next_actions: summary.next_actions
        })
  return { tag: 'pre', kind: 'json', src, jsonText }
}

export function artifactsFromTool(
  _toolName: string,
  args?: Record<string, unknown>
): PreviewArtifact[] {
  const raw = args?.artifacts
  if (!Array.isArray(raw)) return []
  const out: PreviewArtifact[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const rec = item as Record<string, unknown>
    const kind = rec.kind
    const path = rec.path
    if (kind !== 'hero' && kind !== 'gallery' && kind !== 'video' && kind !== 'json') continue
    if (typeof path !== 'string' || path === '') continue
    out.push({
      kind,
      path,
      bytes: typeof rec.bytes === 'number' ? rec.bytes : 0,
      durationSec: typeof rec.durationSec === 'number' ? rec.durationSec : undefined,
      summary: rec.summary as PreviewSummary | undefined
    })
  }
  return out
}

export function toolSourceLabel(toolName: string): 'builtin' | 'cli-hub' | 'generated' {
  if (toolName.startsWith('cli:')) return 'cli-hub'
  if (toolName.startsWith('gen:')) return 'generated'
  return 'builtin'
}
