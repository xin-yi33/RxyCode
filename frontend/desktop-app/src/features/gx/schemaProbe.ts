/** Read-only probe of protocol/schema.json method consts. Never invents methods. */

export type ProbeOutcome = { path: 'A' | 'B'; present: string[]; missing: string[] }

export type BlockedClose = { status: 'BLOCKED_PREREQUISITE'; missing: string[] }

export function extractSchemaMethods(schemaText: string): string[] {
  const found = new Set<string>()
  const re = /"const"\s*:\s*"([^"]+)"/g
  let match: RegExpExecArray | null
  while ((match = re.exec(schemaText)) !== null) {
    found.add(match[1])
  }
  return [...found].sort()
}

export function probeMethods(
  schemaText: string,
  candidates: readonly string[]
): { present: string[]; missing: string[] } {
  const have = new Set(extractSchemaMethods(schemaText))
  const present: string[] = []
  const missing: string[] = []
  for (const name of candidates) {
    if (have.has(name)) present.push(name)
    else missing.push(name)
  }
  return { present, missing }
}

export function blockedPrerequisite(missing: readonly string[]): BlockedClose {
  return { status: 'BLOCKED_PREREQUISITE', missing: [...missing] }
}
