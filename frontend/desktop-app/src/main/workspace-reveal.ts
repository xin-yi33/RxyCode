export interface PathOpener {
  openPath(target: string): Promise<string>
}

export async function revealDirectory(opener: PathOpener, cwd: string): Promise<boolean> {
  const trimmed = cwd.trim()
  if (trimmed === '') return false
  const error = await opener.openPath(trimmed)
  return error === ''
}
