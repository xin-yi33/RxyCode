/**
 * PhaseG-H2 DC-J3: UI entries exist only when handshake capabilities are true.
 */
import { isDeclaredCapability } from '@rxycode/protocol-client'

export type CapabilityName =
  | 'sessions'
  | 'approval'
  | 'models'
  | 'credentials'
  | 'auto_review'
  | 'multi_agent'
  | 'threads'
  | 'thread_fork'

export type UiEntry =
  | 'sessionList'
  | 'approvalModal'
  | 'modelsPanel'
  | 'credentialsPanel'
  | 'autoReview'
  | 'multiAgent'

const ENTRY_CAPABILITY: Record<UiEntry, CapabilityName> = {
  sessionList: 'sessions',
  approvalModal: 'approval',
  modelsPanel: 'models',
  credentialsPanel: 'credentials',
  autoReview: 'auto_review',
  multiAgent: 'multi_agent'
}

export function isUiEntryEnabled(
  capabilities: Readonly<Record<string, unknown>> | null | undefined,
  entry: UiEntry
): boolean {
  return isDeclaredCapability(capabilities, ENTRY_CAPABILITY[entry])
}
