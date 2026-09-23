export type ToolSource = 'builtin' | 'cli-hub' | 'generated'

export interface CliTool {
  id: string
  source: ToolSource
}

export function groupTools(tools: readonly CliTool[], cliBridgeAvailable: boolean): Record<ToolSource, CliTool[]> {
  const groups: Record<ToolSource, CliTool[]> = { builtin: [], 'cli-hub': [], generated: [] }
  for (const tool of tools) {
    const source = cliBridgeAvailable ? tool.source : 'builtin'
    groups[source].push({ ...tool, source })
  }
  if (!cliBridgeAvailable) {
    groups['cli-hub'] = []
    groups.generated = []
  }
  return groups
}

export const PHASE_I_ATTACHMENT_PROTOCOL = false
export const PREVIEW_BUDGET_BYTES = 25 * 1024 * 1024
