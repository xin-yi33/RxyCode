/**
 * PhaseG-H8: Approval UI only submits decisions. Never mutates PermissionPolicy.
 */
import { isDeclaredCapability } from '@rxycode/protocol-client'

export type ApprovalDecision = 'allow' | 'deny' | 'ask' | 'cancel'

export interface ApprovalDisplay {
  approvalId: string
  action: string
  tool: string
  cwd: string
  path?: string
  risk: string
  writes: boolean
  network: boolean
  subprocess: boolean
  scope: string
  expiresAt?: string
  denyConsequence: string
}

export function canShowAutoReview(capabilities: Record<string, unknown> | null): boolean {
  return isDeclaredCapability(capabilities, 'auto_review') || isDeclaredCapability(capabilities, 'approval.auto_review')
}

export function submitDecision(approvalId: string, decision: ApprovalDecision): { method: string; params: Record<string, unknown> } {
  return {
    method: 'approval/respond',
    params: { approval_id: approvalId, decision }
  }
}

export function oneAllowDoesNotGrantNext(previousId: string, nextId: string): boolean {
  return previousId !== nextId
}

export function scopeDoesNotSpread(scope: string, otherProject: string): boolean {
  return scope !== otherProject
}
