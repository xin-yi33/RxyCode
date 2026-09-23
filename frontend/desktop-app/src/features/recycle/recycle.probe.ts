import type { TrashItemModel } from '../../components/TrashItem.ts'
import { projectDisplayName } from '../projects/projectRegistry.ts'
import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

/** B17 recycle contract. session/* is H5, not a substitute. */
export const B17_RECYCLE_METHODS = [
  'thread/list_deleted',
  'thread/restore',
  'thread/purge'
] as const

export function probeRecycle(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
} {
  const result = probeMethods(schemaText, B17_RECYCLE_METHODS)
  return {
    path: result.missing.length === 0 ? 'A' : 'B',
    present: result.present,
    missing: result.missing
  }
}

export function buildThreadRestore(
  schemaText: string,
  threadId: string
): { method: 'thread/restore'; params: { thread_id: string } } | ReturnType<typeof blockedPrerequisite> {
  const probe = probeRecycle(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'thread/restore', params: { thread_id: threadId } }
}

export function buildThreadPurge(
  schemaText: string,
  confirmPurge: boolean
):
  | { error: 'confirm_purge_required' }
  | { method: 'thread/purge'; params: { confirm_purge: true } }
  | ReturnType<typeof blockedPrerequisite> {
  if (!confirmPurge) return { error: 'confirm_purge_required' }
  const probe = probeRecycle(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'thread/purge', params: { confirm_purge: true } }
}

export function recycleSectionModel(input: {
  listDeletedAvailable: boolean
  missing?: readonly string[]
  sessions: readonly {
    sessionId: string
    title: string
    trashedAt: string | number | null
    workspaceRoot?: string
  }[]
}): {
  blocked: boolean
  missing: readonly string[]
  items: TrashItemModel[]
} {
  const items = input.sessions
    .filter((session) => session.trashedAt !== null)
    .map((session) => ({
      id: session.sessionId,
      title: session.title,
      deletedAt: String(session.trashedAt),
      originCategory: 'recent' as const,
      workspaceRoot: session.workspaceRoot ?? ''
    }))
  return {
    blocked: !input.listDeletedAvailable,
    missing: input.listDeletedAvailable ? [] : [...(input.missing ?? B17_RECYCLE_METHODS)],
    items
  }
}

export function formatArchivedAt(value: string, locale = 'zh-CN'): string {
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) return value
  const loc = locale.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
  return new Intl.DateTimeFormat(loc, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).format(new Date(parsed))
}

export function groupArchivedByProject(
  items: readonly TrashItemModel[]
): Array<{ projectKey: string; displayName: string; items: TrashItemModel[] }> {
  const groups = new Map<string, TrashItemModel[]>()
  for (const item of items) {
    const key = item.workspaceRoot?.trim() || '__none__'
    const bucket = groups.get(key) ?? []
    bucket.push(item)
    groups.set(key, bucket)
  }
  return [...groups.entries()].map(([projectKey, grouped]) => ({
    projectKey,
    displayName: projectKey === '__none__' ? 'Recent' : projectDisplayName(projectKey),
    items: grouped
  }))
}

export function filterArchived(
  items: readonly TrashItemModel[],
  query: string,
  projectKey: string
): TrashItemModel[] {
  const needle = query.trim().toLowerCase()
  return items.filter((item) => {
    const matchesQuery = needle === '' || item.title.toLowerCase().includes(needle)
    const matchesProject = projectKey === 'all' || (item.workspaceRoot ?? '') === projectKey
    return matchesQuery && matchesProject
  })
}

export function gx21VisualState(input: {
  loading: boolean
  error: string | null
  empty: boolean
  narrow: boolean
  dark: boolean
}): 'loading' | 'error' | 'empty' | 'narrow' | 'dark' | 'ok' {
  if (input.loading) return 'loading'
  if (input.error !== null) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
