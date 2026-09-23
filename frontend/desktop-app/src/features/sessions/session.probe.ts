import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export const SESSION_MUTATIONS = ['session/rename', 'session/trash', 'session/restore', 'session/purge'] as const
export const THREAD_FORK = 'thread/fork'
export const THREAD_PIN = 'thread/pin'
export const THREAD_ARCHIVE = 'thread/archive'

export function probeSessionOps(schemaText: string): {
  present: string[]
  missing: string[]
  forkPath: 'A' | 'B'
} {
  const result = probeMethods(schemaText, [...SESSION_MUTATIONS, THREAD_FORK, THREAD_PIN, THREAD_ARCHIVE])
  return {
    present: result.present,
    missing: result.missing,
    forkPath: result.present.includes(THREAD_FORK) ? 'A' : 'B'
  }
}

export function buildFork(
  schemaText: string,
  payload: { threadId: string; messageId: string; editedText?: string }
):
  | { method: 'thread/fork'; params: { thread_id: string; message_id: string; edited_text?: string } }
  | ReturnType<typeof blockedPrerequisite> {
  const probe = probeSessionOps(schemaText)
  if (probe.forkPath === 'B') return blockedPrerequisite([THREAD_FORK])
  return {
    method: 'thread/fork',
    params: {
      thread_id: payload.threadId,
      message_id: payload.messageId,
      edited_text: payload.editedText
    }
  }
}

export function canForkFrom(role: string): boolean {
  return role === 'user'
}
