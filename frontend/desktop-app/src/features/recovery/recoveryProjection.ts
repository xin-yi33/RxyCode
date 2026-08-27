export type RecoveryUi = 'ok' | 'recovery_required' | 'reconnecting'

export function projectRecovery(backend: string | null): RecoveryUi {
  if (backend === 'recovery_required') return 'recovery_required'
  if (backend === 'reconnecting') return 'reconnecting'
  return 'ok'
}
