export type PreviewKind = 'code' | 'markdown' | 'image' | 'binary' | 'unknown'

export function classifyPreview(path: string, mime?: string): PreviewKind {
  const lower = path.toLowerCase()
  if (mime?.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/.test(lower)) return 'image'
  if (lower.endsWith('.md')) return 'markdown'
  if (/\.(exe|dll|bin|wasm)$/.test(lower) || mime === 'application/octet-stream') return 'binary'
  if (/\.(ts|tsx|js|py|json|css|html)$/.test(lower)) return 'code'
  return 'unknown'
}

export const PREVIEW_READONLY = true
