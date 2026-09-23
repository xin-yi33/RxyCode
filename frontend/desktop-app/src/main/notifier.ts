/** GX13: Electron main-process notification wrapper. Sanitizes payload. */

export type NotifyTier = 'off' | 'unfocused' | 'always'
export type NotifyKind = 'response' | 'needs_input'

export function sanitizeNoticeBody(text: string): string {
  return text
    .replace(/api[_-]?key\s*[:=]\s*\S+/gi, '[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]+\b/g, '[REDACTED]')
    .slice(0, 80)
}

export function classifyNotify(method: string): NotifyKind | null {
  if (method === 'approval/request' || method === 'question/request') return 'needs_input'
  if (method === 'event/task_complete' || method === 'event/final' || method === 'event/done') return 'response'
  if (method === 'event/message_delta' || method === 'event/token_usage') return null
  return null
}

export function shouldNotify(tier: NotifyTier, focused: boolean, kind: NotifyKind | null): boolean {
  if (kind === null || tier === 'off') return false
  if (tier === 'always') return true
  return !focused
}

export function noticeDedupeKey(kind: NotifyKind, requestId?: string, turnId?: string): string {
  if (kind === 'needs_input') return `need:${requestId ?? 'unknown'}`
  return `resp:${turnId ?? 'unknown'}`
}
