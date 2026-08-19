import { blockedPrerequisite, probeMethods } from '../gx/schemaProbe.ts'

export const SIDE_CHAT_METHODS = ['thread/side_chat/create', 'thread/side_chat/close'] as const

export function probeSideChat(schemaText: string): { path: 'A' | 'B'; missing: string[] } {
  const result = probeMethods(schemaText, SIDE_CHAT_METHODS)
  return { path: result.missing.length === 0 ? 'A' : 'B', missing: result.missing }
}

export function buildSideChatCreate(schemaText: string, threadId: string) {
  const probe = probeSideChat(schemaText)
  if (probe.path === 'B') return blockedPrerequisite(probe.missing)
  return { method: 'thread/side_chat/create', params: { thread_id: threadId } }
}
