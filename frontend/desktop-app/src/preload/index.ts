import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

const api = {
  appserver: {
    getStatus: (): Promise<string> => ipcRenderer.invoke('appserver:get-status'),
    start: (): Promise<string> => ipcRenderer.invoke('appserver:start'),
    stop: (): Promise<string> => ipcRenderer.invoke('appserver:stop'),
    onStatus: (callback: (status: string) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, status: string): void => callback(status)
      ipcRenderer.on('appserver:status', listener)
      return () => {
        ipcRenderer.removeListener('appserver:status', listener)
      }
    },
    onLog: (callback: (line: string) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, line: string): void => callback(line)
      ipcRenderer.on('appserver:log', listener)
      return () => {
        ipcRenderer.removeListener('appserver:log', listener)
      }
    },
    sendLine: (line: string): Promise<void> => ipcRenderer.invoke('appserver:send-line', line),
    onLine: (callback: (line: string) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, line: string): void => callback(line)
      ipcRenderer.on('appserver:line', listener)
      return () => {
        ipcRenderer.removeListener('appserver:line', listener)
      }
    },
    getInfo: (): Promise<{
      repoRoot: string
      protocolVersion: string
      appVersion: string
      appserverPid: number | null
      appserverStatus: string
      homeDir?: string
    }> => ipcRenderer.invoke('appserver:get-info'),
    onLifecycle: (callback: (event: unknown) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, payload: unknown): void => callback(payload)
      ipcRenderer.on('appserver:lifecycle', listener)
      return () => {
        ipcRenderer.removeListener('appserver:lifecycle', listener)
      }
    }
  },
  update: {
    getStatus: () => ipcRenderer.invoke('update:get-status'),
    check: () => ipcRenderer.invoke('update:check'),
    download: () => ipcRenderer.invoke('update:download'),
    install: (): Promise<void> => ipcRenderer.invoke('update:install'),
    onStatus: (callback: (status: unknown) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, status: unknown): void => callback(status)
      ipcRenderer.on('update:status', listener)
      return () => {
        ipcRenderer.removeListener('update:status', listener)
      }
    }
  },
  crashReport: {
    getConsent: (): Promise<boolean> => ipcRenderer.invoke('crash-report:get-consent'),
    setConsent: (enabled: boolean): Promise<void> =>
      ipcRenderer.invoke('crash-report:set-consent', enabled),
    list: () => ipcRenderer.invoke('crash-report:list'),
    onCaptured: (callback: (summary: unknown) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, summary: unknown): void => callback(summary)
      ipcRenderer.on('crash-report:captured', listener)
      return () => {
        ipcRenderer.removeListener('crash-report:captured', listener)
      }
    }
  },
      workspace: {
        pickDirectory: (): Promise<string | null> => ipcRenderer.invoke('workspace:pick-directory'),
        reveal: (cwd: string): Promise<boolean> => ipcRenderer.invoke('workspace:reveal', cwd)
      }
}

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // Isolated+sandboxed BrowserWindow is required (DC-J7); do not expose Node.
  throw new Error('preload requires contextIsolation')
}
