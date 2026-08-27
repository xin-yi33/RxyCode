export interface SearchDoc {
  threadId: string
  title: string
  text: string
  archived?: boolean
  deleted?: boolean
}

export function buildIndex(docs: readonly SearchDoc[]): SearchDoc[] {
  return docs
    .filter((doc) => doc.deleted !== true && doc.archived !== true)
    .map((doc) => ({
      ...doc,
      text: redactSearchText(doc.text)
    }))
}

export function redactSearchText(text: string): string {
  return text
    .replace(/api[_-]?key\s*[:=]\s*\S+/gi, '[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]+\b/g, '[REDACTED]')
}

export function searchIndex(index: readonly SearchDoc[], query: string): SearchDoc[] {
  const q = query.trim().toLowerCase()
  if (q === '') return []
  const hits = index.filter(
    (doc) => doc.title.toLowerCase().includes(q) || doc.text.toLowerCase().includes(q)
  )
  if (hits.length > 0) return hits
  return index.filter((doc) => doc.title.toLowerCase().includes(q))
}
