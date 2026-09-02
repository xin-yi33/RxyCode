export interface TaskTrashDecision {
  allowed: boolean
  message: string | null
}

export function canTrashTask(_activeSessionId: string | null, targetSessionId: string): TaskTrashDecision {
  if (targetSessionId.trim() === '') {
    return { allowed: false, message: '当前任务无法删除' }
  }
  return { allowed: true, message: null }
}

export function isRecoverableConnectionError(message: string): boolean {
  const normalized = message.toLowerCase()
  return normalized.includes('timeout') ||
    normalized.includes('timed out') ||
    normalized.includes('degraded') ||
    normalized.includes('connection') ||
    normalized.includes('pipe')
}
