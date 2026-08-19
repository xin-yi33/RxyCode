export function normalizeGitPath(path: string): string {
  return path.replace(/\\/g, '/')
}
