/**
 * PhaseG-H4: a new Thread must bind an explicit workspace_root.
 * Renderer does not invent Thread records the backend never created.
 */

export interface ThreadWorkspaceBind {
  sessionId: string
  workspaceRoot: string
}

export function bindThreadWorkspace(
  sessionId: string,
  workspaceRoot: string | null | undefined
): ThreadWorkspaceBind | { error: string } {
  const trimmed = typeof workspaceRoot === 'string' ? workspaceRoot.trim() : ''
  if (sessionId.trim() === '') {
    return { error: 'session_id is required' }
  }
  if (trimmed === '') {
    return { error: 'new Thread must bind a workspace_root' }
  }
  return { sessionId, workspaceRoot: trimmed }
}

export function sessionNewParams(workspaceRoot: string, model?: string | null): Record<string, unknown> {
  const params: Record<string, unknown> = { workspace_root: workspaceRoot }
  if (model) params.model = model
  return params
}
