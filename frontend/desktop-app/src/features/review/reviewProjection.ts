/**
 * PhaseG-H9: Review/Finding/Checkpoint are displayed, never recomputed.
 */

export interface FindingView {
  id: string
  path: string
  line: number
  diffHash: string
  stale: boolean
  comment?: string
}

export interface ReviewView {
  reviewId: string
  findings: FindingView[]
  status: 'running' | 'completed' | 'failed' | 'stale'
}

export function startReviewRequest(sessionId: string): { method: 'review/start'; params: { session_id: string } } {
  return { method: 'review/start', params: { session_id: sessionId } }
}

export function mustNotForgeReview(uiWantsPass: boolean, backend: ReviewView | null): boolean {
  return backend !== null && uiWantsPass === (backend.status === 'completed')
}

export function checkpointRestore(id: string): { method: string; params: { checkpoint_id: string } } {
  return { method: 'checkpoint/restore', params: { checkpoint_id: id } }
}
