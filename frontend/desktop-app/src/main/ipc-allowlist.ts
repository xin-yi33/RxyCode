/**
 * PhaseG-H3: preload/main IPC allowlist and argument schema.
 * Unknown methods and invalid params are rejected. No ipcRenderer leak.
 */

export const IPC_INVOKE_CHANNELS = [
  'appserver:get-status',
  'appserver:start',
  'appserver:stop',
  'appserver:send-line',
  'appserver:get-info',
  'workspace:pick-directory',
  'update:get-status',
  'update:check',
  'update:download',
  'update:install',
  'crash-report:get-consent',
  'crash-report:set-consent',
  'crash-report:list'
] as const

export type IpcInvokeChannel = (typeof IPC_INVOKE_CHANNELS)[number]

export const IPC_EVENT_CHANNELS = [
  'appserver:status',
  'appserver:log',
  'appserver:line',
  'appserver:lifecycle',
  'update:status',
  'crash-report:captured'
] as const

export type IpcValidationResult =
  | { ok: true }
  | { ok: false; code: 'unknown_method' | 'invalid_params'; message: string }

export class IpcAllowlistError extends Error {
  readonly code: 'unknown_method' | 'invalid_params'

  constructor(result: Extract<IpcValidationResult, { ok: false }>) {
    super(result.message)
    this.name = 'IpcAllowlistError'
    this.code = result.code
  }
}

export function isAllowedIpcChannel(channel: string): channel is IpcInvokeChannel {
  return (IPC_INVOKE_CHANNELS as readonly string[]).includes(channel)
}

export function validateIpcInvoke(channel: string, args: unknown[]): IpcValidationResult {
  if (!isAllowedIpcChannel(channel)) {
    return { ok: false, code: 'unknown_method', message: `unknown IPC method: ${channel}` }
  }
  switch (channel) {
    case 'appserver:send-line':
      if (args.length !== 1 || typeof args[0] !== 'string') {
        return { ok: false, code: 'invalid_params', message: 'appserver:send-line requires a string' }
      }
      return { ok: true }
    case 'crash-report:set-consent':
      if (args.length !== 1 || typeof args[0] !== 'boolean') {
        return { ok: false, code: 'invalid_params', message: 'crash-report:set-consent requires a boolean' }
      }
      return { ok: true }
    default:
      if (args.length > 0) {
        return { ok: false, code: 'invalid_params', message: `${channel} takes no arguments` }
      }
      return { ok: true }
  }
}

export function assertIpcInvoke(channel: string, args: unknown[]): void {
  const result = validateIpcInvoke(channel, args)
  if (!result.ok) {
    throw new IpcAllowlistError(result)
  }
}

export function registerAllowedHandle(
  ipcMain: { handle: (channel: string, listener: (...args: any[]) => unknown) => void },
  channel: IpcInvokeChannel,
  listener: (event: unknown, ...args: unknown[]) => unknown
): void {
  ipcMain.handle(channel, (event: unknown, ...args: unknown[]) => {
    assertIpcInvoke(channel, args)
    return listener(event, ...args)
  })
}
