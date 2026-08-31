export interface CapabilityRow {
  capabilityId: string
  kind: string
  name: string
  installed: boolean
  enabled: boolean
  authorized: boolean
  available: boolean
  connection: string
  error: string | null
  origin: string
  description: string
  scope: string
  body: string
}

export function mapCapabilityRow(raw: Record<string, unknown>): CapabilityRow {
  return {
    capabilityId: String(raw.capability_id ?? ''),
    kind: String(raw.kind ?? ''),
    name: String(raw.name ?? raw.capability_id ?? ''),
    installed: raw.installed === true,
    enabled: raw.enabled === true,
    authorized: raw.authorized !== false,
    available: raw.available === true,
    connection: String(raw.connection ?? ''),
    error: raw.error == null || raw.error === '' ? null : String(raw.error),
    origin: String(raw.origin ?? ''),
    description: String(raw.description ?? ''),
    scope: String(raw.scope ?? ''),
    body: String(raw.body ?? '')
  }
}

export function parseCapabilitiesList(raw: unknown): CapabilityRow[] {
  if (raw == null || typeof raw !== 'object') return []
  const list = (raw as { capabilities?: unknown }).capabilities
  if (!Array.isArray(list)) return []
  return list
    .filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
    .map(mapCapabilityRow)
    .filter((row) => row.capabilityId !== '')
}
