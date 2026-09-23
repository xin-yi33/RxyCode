import { resolveDesktopView, type DesktopViewEntry } from './views/index.ts'

export function parseViewFromSearch(search: string): DesktopViewEntry {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  return resolveDesktopView(params.get('view'))
}

export function viewSearch(viewId: string): string {
  return `?view=${encodeURIComponent(viewId)}`
}
