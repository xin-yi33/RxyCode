import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export type ReviewScope = 'unstaged' | 'staged' | 'commit' | 'branch' | 'last_turn'
export type CommentStatus = 'open' | 'resolved' | 'stale'

export const REVIEW_SCOPES: readonly ReviewScope[] = [
  'unstaged',
  'staged',
  'commit',
  'branch',
  'last_turn'
]

export const COMMENT_METHODS = ['review/comment/add', 'review/comment/resolve'] as const

export interface InlineCommentRecord {
  id: string
  file: string
  line: number
  hunkHash: string
  body: string
  status: CommentStatus
}

export function probeReviewComments(schemaText: string): {
  path: 'A' | 'B'
  present: string[]
  missing: string[]
} {
  const result = probeMethods(schemaText, COMMENT_METHODS)
  return { path: result.missing.length === 0 ? 'A' : 'B', ...result }
}

export function markStale(comment: InlineCommentRecord, currentHunkHash: string): InlineCommentRecord {
  if (comment.status === 'resolved') return comment
  if (comment.hunkHash !== currentHunkHash && comment.status === 'open') {
    return { ...comment, status: 'stale' }
  }
  return comment
}

export function resolveComment(comment: InlineCommentRecord): InlineCommentRecord {
  return { ...comment, status: 'resolved' }
}

export function canReopen(comment: InlineCommentRecord): boolean {
  return comment.status === 'open'
}

export function buildCommentAdd(
  schemaText: string,
  payload: { reviewId: string; file: string; line: number; hunkHash: string; body: string }
):
  | { method: 'review/comment/add'; params: typeof payload }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeReviewComments(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'review/comment/add', params: payload }
}

export function draftFromComments(comments: readonly InlineCommentRecord[]): string {
  const open = comments.filter((c) => c.status === 'open')
  if (open.length === 0) return ''
  return `请处理以下内联评论：\n${open.map((c) => `- ${c.file}:${c.line} ${c.body}`).join('\n')}`
}

export function gx3VisualState(input: {
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
