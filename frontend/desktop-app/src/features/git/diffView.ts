export interface DiffHunk {
  path: string
  hash: string
  lines: string[]
  folded: boolean
}

export function foldLongLine(line: string, max = 200): string {
  if (line.length <= max) return line
  return `${line.slice(0, max)}…`
}

export function emptyDiffState(): 'empty' | 'error' | 'ready' {
  return 'empty'
}
