export type BackendRun = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
export type StatusVisual = 'spin' | 'dot' | 'error' | 'idle'

export function fromSessionRunState(state: string): BackendRun {
  if (state === 'succeeded') return 'completed'
  if (state === 'approval') return 'running'
  if (state === 'queued' || state === 'running' || state === 'failed' || state === 'cancelled' || state === 'timed_out') {
    return state
  }
  return 'cancelled'
}

export function projectStatus(backend: BackendRun): StatusVisual {
  if (backend === 'running' || backend === 'queued') return 'spin'
  if (backend === 'completed') return 'dot'
  if (backend === 'failed' || backend === 'timed_out') return 'error'
  return 'idle'
}

export function runningHighlight(backend: BackendRun): boolean {
  return backend === 'running'
}

export function sessionRowChrome(input: {
  runState?: string
  running?: boolean
  unread?: boolean
}): 'spin' | 'unread' | 'idle' {
  if (input.running === true) return 'spin'
  const backend = fromSessionRunState(input.runState ?? 'cancelled')
  if (backend === 'running') return 'spin'
  if (input.unread === true) return 'unread'
  return 'idle'
}

export function statusVisualState(input: {
  empty: boolean
  loading: boolean
  error: boolean
  narrow: boolean
  dark: boolean
}): 'empty' | 'loading' | 'error' | 'narrow' | 'dark' | 'ok' {
  if (input.loading) return 'loading'
  if (input.error) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
