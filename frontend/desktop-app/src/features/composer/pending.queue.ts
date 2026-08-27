export type SendIntent = 'queue' | 'steer' | 'stop_and_send'

export interface PendingItem {
  id: string
  text: string
}

export const PENDING_LIMIT = 10

export function pushPending(queue: readonly PendingItem[], item: PendingItem): PendingItem[] {
  if (queue.length >= PENDING_LIMIT) return [...queue]
  if (item.text.trim() === '') return [...queue]
  return [...queue, item]
}

export function removePending(queue: readonly PendingItem[], id: string): PendingItem[] {
  return queue.filter((item) => item.id !== id)
}

export function reorderPending(queue: readonly PendingItem[], from: number, to: number): PendingItem[] {
  if (from < 0 || to < 0 || from >= queue.length || to >= queue.length) return [...queue]
  const next = [...queue]
  const [moved] = next.splice(from, 1)
  if (moved === undefined) return next
  next.splice(to, 0, moved)
  return next
}

export function shortcutIntent(event: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; key: string }): SendIntent | null {
  if (event.key !== 'Enter') return null
  if (event.altKey) return 'queue'
  if (event.ctrlKey || event.metaKey) return 'stop_and_send'
  return null
}

export function gx5VisualState(input: {
  running: boolean
  queueLength: number
  error: string | null
  narrow: boolean
  dark: boolean
}): 'idle' | 'running' | 'queued' | 'error' | 'narrow' | 'dark' {
  if (input.error !== null) return 'error'
  if (input.narrow) return 'narrow'
  if (input.dark && !input.running && input.queueLength === 0) return 'dark'
  if (input.queueLength > 0) return 'queued'
  if (input.running) return 'running'
  return 'idle'
}
