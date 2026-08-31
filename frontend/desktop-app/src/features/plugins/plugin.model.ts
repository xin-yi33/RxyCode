export interface PluginRecord {
  name: string
  version: string
  source: string
  enabled: boolean
  path: string
  description: string
  auth: string
}

export function mapPluginRecord(raw: Record<string, unknown>): PluginRecord {
  const manifest = (raw.manifest as Record<string, unknown> | undefined) ?? {}
  const description =
    typeof raw.description === 'string'
      ? raw.description
      : typeof manifest.description === 'string'
        ? manifest.description
        : ''
  return {
    name: String(raw.name ?? ''),
    version: String(raw.version ?? ''),
    source: String(raw.source ?? ''),
    enabled: raw.enabled !== false,
    path: String(raw.path ?? ''),
    description,
    auth: typeof raw.auth === 'string' ? raw.auth : ''
  }
}

export function githubCardState(
  row?: Pick<PluginRecord, 'name' | 'auth'> | null
): 'install' | 'connect' | 'connected' {
  if (row == null || row.name.toLowerCase() !== 'github') return 'install'
  if (row.auth === 'configured') return 'connected'
  return 'connect'
}

export function parsePluginList(raw: unknown): PluginRecord[] {
  if (raw == null || typeof raw !== 'object') return []
  const list = (raw as { plugins?: unknown }).plugins
  if (!Array.isArray(list)) return []
  return list
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map(mapPluginRecord)
    .filter((row) => row.name !== '')
}

export const GITHUB_PLUGIN = {
  name: 'github',
  title: 'GitHub',
  description: '连接 GitHub 仓库、Issues 与 Pull Request'
}
