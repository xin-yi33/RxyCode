export type NoticeKind = 'turn' | 'approval' | 'input' | 'failure' | 'stop'

export interface Notice {
  id: string
  kind: NoticeKind
  title: string
  body: string
}

export type OsNotifyFn = (title: string, body: string) => boolean

export function dedupeNotices(existing: readonly Notice[], incoming: Notice): Notice[] {
  if (existing.some((notice) => notice.id === incoming.id)) return [...existing]
  return [...existing, incoming]
}

export function osNotificationAvailable(): boolean {
  return typeof Notification === 'function'
}

/** Windows toast / macOS UserNotifications / Linux libnotify via Electron. */
export function electronOsNotify(title: string, body: string): boolean {
  if (typeof Notification !== 'function') return false
  try {
    new Notification(title, { body })
    return true
  } catch {
    return false
  }
}

export function noticeForRunEnd(
  sessionId: string,
  state: 'cancelled' | 'failed' | 'timed_out'
): Notice {
  if (state === 'cancelled') {
    return { id: `stop:${sessionId}`, kind: 'stop', title: 'Task stopped', body: sessionId }
  }
  return { id: `fail:${sessionId}:${state}`, kind: 'failure', title: 'Task failed', body: `${sessionId} ${state}` }
}

export function watchRunStateTransitions(
  prev: Record<string, string>,
  next: Record<string, string>
): Array<{ sessionId: string; state: 'cancelled' | 'failed' | 'timed_out' }> {
  const out: Array<{ sessionId: string; state: 'cancelled' | 'failed' | 'timed_out' }> = []
  for (const [sessionId, state] of Object.entries(next)) {
    if (prev[sessionId] !== 'running') continue
    if (state === 'cancelled' || state === 'failed' || state === 'timed_out') {
      out.push({ sessionId, state })
    }
  }
  return out
}

export function dispatchRunEndNotice(
  sessionId: string,
  state: string,
  deps: { osNotify: OsNotifyFn; showBanner: (notice: Notice) => void }
): 'os' | 'banner' | 'skip' {
  if (state !== 'cancelled' && state !== 'failed' && state !== 'timed_out') return 'skip'
  const notice = noticeForRunEnd(sessionId, state)
  try {
    if (deps.osNotify(notice.title, notice.body)) return 'os'
  } catch {
    // Linux without libnotify: Electron Notification throws.
  }
  deps.showBanner(notice)
  return 'banner'
}
