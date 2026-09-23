import type { RunPanelModel } from './RunPanel.ts'

export interface RunPanelSource {
  planBySession: Record<string, string[]>
  progressBySession: Record<string, string>
  usageBySession: Record<
    string,
    {
      inputTokens: number | null
      outputTokens: number | null
      reportingStatus: string
    }
  >
  timelineBySession: Record<string, Array<{ kind: string; toolName?: string; arguments?: Record<string, unknown> }>>
  runningBySession: Record<string, boolean>
}

const FILE_TOOLS = new Set(['write', 'edit', 'patch', 'apply_patch'])

export function projectRunPanel(
  state: RunPanelSource,
  sessionId: string
): {
  model: RunPanelModel
  open: boolean
  usageAvailable: boolean
} {
  const running = state.runningBySession[sessionId] === true
  const usage = state.usageBySession[sessionId]
  const files = (state.timelineBySession[sessionId] ?? [])
    .filter((item) => item.kind === 'tool_activity' && FILE_TOOLS.has(item.toolName ?? ''))
    .map((item) => {
      const path = item.arguments?.path
      return typeof path === 'string' ? path : null
    })
    .filter((path): path is string => path !== null)
  return {
    open: running,
    usageAvailable: usage?.reportingStatus === 'reported' || usage?.reportingStatus === 'partial',
    model: {
      plan: (state.planBySession[sessionId] ?? []).join('\n'),
      sources: [],
      files: [...new Set(files)],
      tokensUsed: (usage?.inputTokens ?? 0) + (usage?.outputTokens ?? 0),
      step: state.progressBySession[sessionId],
      running
    }
  }
}
