/** PhaseG-H11: max tokens only from Phase 3 resolver/summary. */
export interface ModelSummary {
  id: string
  resolved_max_tokens?: number | null
  limit_source?: string | null
}

export function displayMaxTokens(model: ModelSummary): string {
  if (model.resolved_max_tokens == null) return '—'
  const source = model.limit_source ?? 'resolver'
  return `${model.resolved_max_tokens} (${source})`
}

export function inferMaxTokensFromId(_id: string): never {
  throw new Error('max tokens must not be inferred from model id')
}
