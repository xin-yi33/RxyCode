import { ElectronAPI } from '@electron-toolkit/preload'

type UpdateStatus =
  | 'disabled'
  | 'idle'
  | 'checking'
  | 'available'
  | 'not-available'
  | 'downloading'
  | 'downloaded'
  | 'error'

interface UpdateProgress {
  percent: number
  transferred: number
  total: number
}

interface UpdateStatusSnapshot {
  status: UpdateStatus
  currentVersion: string
  availableVersion: string | null
  error: string | null
  progress: UpdateProgress | null
}

interface CrashReportSummary {
  id: string
  capturedAt: string
  source: string
  path: string
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: {
      appserver: {
        getStatus: () => Promise<string>
        start: () => Promise<string>
        stop: () => Promise<string>
        onStatus: (callback: (status: string) => void) => () => void
        onLog: (callback: (line: string) => void) => () => void
        sendLine: (line: string) => Promise<void>
        onLine: (callback: (line: string) => void) => () => void
        onLifecycle: (callback: (event: unknown) => void) => () => void
        getInfo: () => Promise<{
          repoRoot: string
          protocolVersion: string
          appVersion: string
          appserverPid: number | null
          appserverStatus: string
          systemLocale?: string
        }>
      }
      update: {
        getStatus: () => Promise<UpdateStatusSnapshot>
        check: () => Promise<UpdateStatusSnapshot>
        download: () => Promise<UpdateStatusSnapshot>
        install: () => Promise<void>
        onStatus: (callback: (status: UpdateStatusSnapshot) => void) => () => void
      }
      crashReport: {
        getConsent: () => Promise<boolean>
        setConsent: (enabled: boolean) => Promise<void>
        list: () => Promise<CrashReportSummary[]>
        onCaptured: (callback: (summary: CrashReportSummary) => void) => () => void
      }
      workspace: {
        pickDirectory: () => Promise<string | null>
      }
    }
  }
}
