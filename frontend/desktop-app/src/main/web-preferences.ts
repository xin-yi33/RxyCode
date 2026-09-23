/**
 * PhaseG-H3 DC-J7 defaults. BrowserWindow must not loosen these.
 */
export function webPreferencesSafe(
  extra: Record<string, unknown> = {}
): {
  contextIsolation: true
  nodeIntegration: false
  sandbox: true
  preload?: string
} {
  const merged = {
    ...extra,
    contextIsolation: true as const,
    nodeIntegration: false as const,
    sandbox: true as const
  }
  return merged
}
