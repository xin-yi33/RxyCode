export type BackendRun = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
export type StatusVisual = 'spin' | 'dot' | 'error' | 'idle'

export function projectStatus(backend: BackendRun): StatusVisual {
  if (backend === 'running' || backend === 'queued') return 'spin'
  if (backend === 'completed') return 'dot'
  if (backend === 'failed' || backend === 'timed_out') return 'error'
  return 'idle'
}

export function runningHighlight(backend: BackendRun): boolean {
  return backend === 'running'
}
