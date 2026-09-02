/**
 * Desktop platform adapter (Phase4-D2, DC3).
 *
 * This is the only layer that touches the Electron preload bridge
 * (window.api.*). Renderer hooks and components depend on the interfaces
 * below instead of calling window.api directly, keeping the UI swappable
 * (e.g. a Tauri host later) and the Electron specifics in one place.
 *
 * The main process only forwards raw stdin/stdout lines and owns no
 * JSON-RPC request ids; the renderer's ProtocolClient is the single owner
 * of the id space (no shared ids with main).
 */
import { useEffect, useState } from 'react'
import {
  ProtocolClient,
  PROTOCOL_VERSION_MAX,
  PROTOCOL_VERSION_MIN,
  initializeHandshake,
  type HandshakeState,
  type NotificationHandler,
  type ServerRequestHandler
} from '@rxycode/protocol-client'

export type AppserverStatus = 'stopped' | 'starting' | 'running' | 'crashed'

export interface AppserverInfo {
  repoRoot: string
  protocolVersion: string
  appVersion: string
  appserverPid?: number | null
  appserverStatus?: string
  systemLocale?: string
  homeDir?: string
}

export interface AppserverPlatform {
  getInfo(): Promise<AppserverInfo>
  getStatus(): Promise<AppserverStatus>
  start(): void
  stop(): void
  restart?: () => Promise<void>
  pickWorkspaceDirectory(): Promise<string | null>
  revealWorkspace?(cwd: string): Promise<boolean>
  onStatus(callback: (status: AppserverStatus) => void): () => void
  sendLine(line: string): void
  onLine(callback: (line: string) => void): () => void
}

export function createAppserverPlatform(): AppserverPlatform {
  return {
    getInfo: () => window.api.appserver.getInfo(),
    getStatus: () => window.api.appserver.getStatus().then((status) => status as AppserverStatus),
    start: () => {
      void window.api.appserver.start()
    },
    stop: () => {
      void window.api.appserver.stop()
    },
    restart: async () => {
      await window.api.appserver.stop()
      await window.api.appserver.start()
    },
    pickWorkspaceDirectory: () => window.api.workspace.pickDirectory(),
    revealWorkspace: (cwd: string) => window.api.workspace.reveal(cwd),
    onStatus: (callback) =>
      window.api.appserver.onStatus((status) => callback(status as AppserverStatus)),
    sendLine: (line) => {
      void window.api.appserver.sendLine(line)
    },
    onLine: (callback) => window.api.appserver.onLine(callback)
  }
}

export interface UsePlatformResult {
  platform: AppserverPlatform
  info: AppserverInfo | null
  status: AppserverStatus
}

export function usePlatform(): UsePlatformResult {
  const [platform] = useState<AppserverPlatform>(createAppserverPlatform)
  const [info, setInfo] = useState<AppserverInfo | null>(null)
  const [status, setStatus] = useState<AppserverStatus>('stopped')

  useEffect(() => {
    let mounted = true
    void platform.getInfo().then((value) => {
      if (mounted) setInfo(value)
    })
    void platform.getStatus().then((value) => {
      if (mounted) setStatus(value)
    })
    const offStatus = platform.onStatus((value) => {
      if (mounted) setStatus(value)
    })
    return () => {
      mounted = false
      offStatus()
    }
  }, [platform])

  return { platform, info, status }
}

export interface ConversationConnectionOptions {
  platform: AppserverPlatform
  onNotification: NotificationHandler
  onServerRequest?: ServerRequestHandler
  onServerRequestAborted?: (error: Error) => void
  initializeTimeoutMs?: number
  initializeMaxAttempts?: number
  initializeRetryDelayMs?: number
  onConnectionError?: (error: Error) => void
}

export interface ConversationConnection {
  readonly client: ProtocolClient | null
  readonly handshake: HandshakeState
  attach(info: AppserverInfo): Promise<void>
  reconnect(info: AppserverInfo): Promise<void>
  detach(reason: string): void
}

/**
 * Owns the renderer-side ProtocolClient and binds it to the appserver
 * lifecycle: attach() when the server is running, detach() when it is
 * stopped/crashed. attach() runs initialize with a timeout so a silent
 * server cannot wedge the UI.
 */
export function createConversationConnection(
  options: ConversationConnectionOptions
): ConversationConnection {
  let client: ProtocolClient | null = null
  let offLine: (() => void) | null = null
  let handshake: HandshakeState = { status: 'pending' }

  return {
    get client() {
      return client
    },
    get handshake() {
      return handshake
    },
    async attach(info: AppserverInfo): Promise<void> {
      if (client !== null) return
      const next = new ProtocolClient((line) => options.platform.sendLine(line))
      next.onNotification = options.onNotification
      next.onServerRequest = options.onServerRequest
      const unsubscribe = options.platform.onLine((line) => {
        void next.handleLine(line)
      })
      client = next
      offLine = unsubscribe
      handshake = { status: 'started' }
      const maxAttempts = options.initializeMaxAttempts ?? 3
      const retryDelayMs = options.initializeRetryDelayMs ?? 250
      try {
        let lastError: Error = new Error('initialize failed')
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
          if (client !== next) throw lastError
          const state = await initializeHandshake(
            next,
            {
              client_name: 'rxycode-desktop',
              client_version: info.appVersion,
              protocol_version: info.protocolVersion,
              capabilities: { desktop: true }
            },
            {
              timeoutMs: options.initializeTimeoutMs ?? 10_000,
              versionRange: {
                min: PROTOCOL_VERSION_MIN,
                max: PROTOCOL_VERSION_MAX
              }
            }
          )
          handshake = state
          if (state.status === 'completed') {
            return
          }
          if (state.status !== 'failed') {
            lastError = new Error('initialize failed')
            throw lastError
          }
          lastError = new Error(state.error.message)
          if (client !== next) throw lastError
          const retry = state.error.handling === 'retry' && attempt < maxAttempts - 1
          if (!retry) {
            throw lastError
          }
          await new Promise((resolveWait) => setTimeout(resolveWait, retryDelayMs))
        }
        throw lastError
      } catch (error) {
        if (client === next) {
          unsubscribe()
          next.rejectAllPending(error instanceof Error ? error : new Error(String(error)))
          client = null
          offLine = null
          const wrapped = error instanceof Error ? error : new Error(String(error))
          if (handshake.status !== 'failed') {
            handshake = { status: 'failed', error: { code: 'rpc_error', handling: 'retry', message: wrapped.message } }
          }
          options.onConnectionError?.(wrapped)
          options.onServerRequestAborted?.(wrapped)
          throw wrapped
        }
        throw error
      }
    },
    async reconnect(info: AppserverInfo): Promise<void> {
      this.detach('reconnecting to appserver')
      await this.attach(info)
    },
    detach(reason: string): void {
      if (client === null) return
      offLine?.()
      client.rejectAllPending(new Error(reason))
      client = null
      offLine = null
      options.onServerRequestAborted?.(new Error(reason))
    }
  }
}

export type UpdateStatus =
  | 'disabled'
  | 'idle'
  | 'checking'
  | 'available'
  | 'not-available'
  | 'downloading'
  | 'downloaded'
  | 'error'

export interface UpdateProgress {
  percent: number
  transferred: number
  total: number
}

export interface UpdateStatusSnapshot {
  status: UpdateStatus
  currentVersion: string
  availableVersion: string | null
  error: string | null
  progress: UpdateProgress | null
}

export interface CrashReportSummary {
  id: string
  capturedAt: string
  source: string
  path: string
}

export interface DiagnosticsPlatform {
  getUpdateStatus(): Promise<UpdateStatusSnapshot>
  checkForUpdates(): Promise<UpdateStatusSnapshot>
  downloadUpdate(): Promise<UpdateStatusSnapshot>
  installUpdate(): void
  onUpdateStatus(callback: (snapshot: UpdateStatusSnapshot) => void): () => void
  getCrashConsent(): Promise<boolean>
  setCrashConsent(enabled: boolean): Promise<void>
  listCrashReports(): Promise<CrashReportSummary[]>
  onCrashCaptured(callback: (summary: CrashReportSummary) => void): () => void
}

/**
 * Renderer-facing bridge for the "更新与诊断" settings tab (Phase4-D7,
 * DC3: all Electron specifics stay behind the platform adapter).
 */
export function createDiagnosticsPlatform(): DiagnosticsPlatform {
  return {
    getUpdateStatus: () => window.api.update.getStatus(),
    checkForUpdates: () => window.api.update.check(),
    downloadUpdate: () => window.api.update.download(),
    installUpdate: () => {
      void window.api.update.install()
    },
    onUpdateStatus: (callback) => window.api.update.onStatus(callback),
    getCrashConsent: () => window.api.crashReport.getConsent(),
    setCrashConsent: (enabled) => window.api.crashReport.setConsent(enabled),
    listCrashReports: () => window.api.crashReport.list(),
    onCrashCaptured: (callback) => window.api.crashReport.onCaptured(callback)
  }
}

export interface UseDiagnosticsResult {
  updateStatus: UpdateStatusSnapshot | null
  consent: boolean | null
  reports: CrashReportSummary[]
  checkForUpdates(): Promise<void>
  downloadUpdate(): Promise<void>
  installUpdate(): void
  setConsent(enabled: boolean): Promise<void>
  refresh(): Promise<void>
}

export function useDiagnostics(): UseDiagnosticsResult {
  const [platform] = useState<DiagnosticsPlatform>(createDiagnosticsPlatform)
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusSnapshot | null>(null)
  const [consent, setConsentState] = useState<boolean | null>(null)
  const [reports, setReports] = useState<CrashReportSummary[]>([])

  useEffect(() => {
    let mounted = true
    const initialRefresh = async (): Promise<void> => {
      const [status, currentConsent, currentReports] = await Promise.all([
        platform.getUpdateStatus(),
        platform.getCrashConsent(),
        platform.listCrashReports()
      ])
      if (!mounted) return
      setUpdateStatus(status)
      setConsentState(currentConsent)
      setReports(currentReports)
    }
    void initialRefresh()
    const offStatus = platform.onUpdateStatus((snapshot) => {
      if (mounted) setUpdateStatus(snapshot)
    })
    const offCaptured = platform.onCrashCaptured(() => {
      void platform.listCrashReports().then((next) => {
        if (mounted) setReports(next)
      })
    })
    return () => {
      mounted = false
      offStatus()
      offCaptured()
    }
  }, [platform])

  return {
    updateStatus,
    consent,
    reports,
    checkForUpdates: async () => {
      const next = await platform.checkForUpdates()
      setUpdateStatus(next)
    },
    downloadUpdate: async () => {
      const next = await platform.downloadUpdate()
      setUpdateStatus(next)
    },
    installUpdate: () => platform.installUpdate(),
    setConsent: async (enabled: boolean) => {
      await platform.setCrashConsent(enabled)
      setConsentState(enabled)
    },
    refresh: async () => {
      const [status, currentConsent, currentReports] = await Promise.all([
        platform.getUpdateStatus(),
        platform.getCrashConsent(),
        platform.listCrashReports()
      ])
      setUpdateStatus(status)
      setConsentState(currentConsent)
      setReports(currentReports)
    }
  }
}
