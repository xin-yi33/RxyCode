const KEY = /\bsk-[A-Za-z0-9_-]+\b|api[_-]?key["']?\s*[:=]\s*["']?[^,"}\s]+/gi

export function stripSecrets(text: string): string {
  return text.replace(KEY, '[REDACTED]')
}

export function assertNoSecret(payload: unknown): boolean {
  const raw = JSON.stringify(payload ?? null)
  return stripSecrets(raw) === raw
}
