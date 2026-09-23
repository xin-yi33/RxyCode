import type { ModelEntry } from '../hooks/useModels'

export function modelGroupLabel(model: Pick<ModelEntry, 'provider_name' | 'provider_id' | 'category'>): string {
  const providerName = model.provider_name?.trim() ?? ''
  const providerId = model.provider_id?.trim().toLowerCase() ?? ''
  if (providerName === '' || providerId === 'custom' || providerName === '其他') return 'Others'
  return providerName || model.category?.trim() || 'Others'
}

export const MISSING_CREDENTIAL_WARNING = 'API credential is unavailable'

export function modelHasCredential(model: Pick<ModelEntry, 'warning'>): boolean {
  return !String(model.warning ?? '').includes(MISSING_CREDENTIAL_WARNING)
}

export function duplicateModelNicknames(models: readonly Pick<ModelEntry, 'nickname' | 'name' | 'provider_model_id'>[]): Set<string> {
  const counts = new Map<string, number>()
  for (const model of models) {
    const nick = model.nickname || model.name || model.provider_model_id
    counts.set(nick, (counts.get(nick) ?? 0) + 1)
  }
  return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([nick]) => nick))
}

export function modelPickerLabel(
  model: Pick<ModelEntry, 'id' | 'name' | 'nickname' | 'provider_model_id' | 'warning'>,
  duplicates: ReadonlySet<string>,
  missingSuffix = 'no key'
): string {
  const nick = model.nickname || model.name || model.provider_model_id
  const base = duplicates.has(nick) ? `${nick} (${model.id})` : nick
  return modelHasCredential(model) ? base : `${base} · ${missingSuffix}`
}

export function groupModelsByProvider(models: ModelEntry[]): Array<[string, ModelEntry[]]> {
  const groups = new Map<string, ModelEntry[]>()
  for (const model of models) {
    const label = modelGroupLabel(model)
    const entries = groups.get(label) ?? []
    entries.push(model)
    groups.set(label, entries)
  }
  return [...groups.entries()]
}
