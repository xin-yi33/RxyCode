export type NoticeKind = 'turn' | 'approval' | 'input' | 'failure' | 'stop'

export interface Notice {
  id: string
  kind: NoticeKind
  title: string
  body: string
}

export function dedupeNotices(existing: readonly Notice[], incoming: Notice): Notice[] {
  if (existing.some((notice) => notice.id === incoming.id)) return [...existing]
  return [...existing, incoming]
}

export function osNotificationAvailable(): boolean {
  return typeof Notification !== 'undefined'
}

export function notifyOrBanner(notice: Notice, notify?: (title: string, body: string) => void): 'os' | 'banner' {
  if (notify) {
    notify(notice.title, notice.body)
    return 'os'
  }
  return 'banner'
}
