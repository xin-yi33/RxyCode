import { removePending, type PendingItem } from './pending.queue.ts'

export type QueueMode = 'on' | 'off'

export function queueOnEnter(running: boolean, queueMode: QueueMode): boolean {
  return running && queueMode === 'on'
}

export function takePendingById(
  queue: readonly PendingItem[],
  id: string
): { item: PendingItem | null; remaining: PendingItem[] } {
  const item = queue.find((row) => row.id === id) ?? null
  return { item, remaining: removePending(queue, id) }
}
