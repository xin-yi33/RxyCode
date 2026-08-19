/**
 * PhaseG-H3 appserver connection supervisor.
 * One manager is shared by every window. UI only projects backend lifecycle.
 */

import { EventEmitter } from 'node:events'
import { AppServerManager, type AppserverExitInfo, type AppserverStatus } from './appserver.ts'

export const PROCESS_LIFECYCLE_METHODS = [
  'event/process_started',
  'event/process_shutdown',
  'event/process_failed',
  'event/recovery_required',
  'event/recovery_started'
] as const

export type ProcessLifecycleMethod = (typeof PROCESS_LIFECYCLE_METHODS)[number]

export interface ProcessLifecycleEvent {
  method: ProcessLifecycleMethod
  params: Record<string, unknown>
}

export interface SupervisorSnapshot {
  status: AppserverStatus
  pid: number | null
  windowCount: number
  lastExit: AppserverExitInfo | null
  lastLifecycle: ProcessLifecycleEvent | null
  recoveryRequired: boolean
  startFailures: number
}

export interface AppserverLike {
  status: AppserverStatus
  readonly pid: number | null
  start(): boolean
  stop(): Promise<void>
  kill(): void
  on(event: string, listener: (...args: unknown[]) => void): unknown
  off?(event: string, listener: (...args: unknown[]) => void): unknown
}

export function isProcessLifecycleMethod(method: unknown): method is ProcessLifecycleMethod {
  return (
    typeof method === 'string' &&
    (PROCESS_LIFECYCLE_METHODS as readonly string[]).includes(method)
  )
}

export function lifecycleFromProtocolMessage(message: unknown): ProcessLifecycleEvent | null {
  if (message === null || typeof message !== 'object') return null
  const record = message as { method?: unknown; params?: unknown }
  if (!isProcessLifecycleMethod(record.method)) return null
  const params =
    record.params !== null && typeof record.params === 'object'
      ? (record.params as Record<string, unknown>)
      : {}
  return { method: record.method, params }
}

export class ProcessSupervisor extends EventEmitter {
  readonly manager: AppserverLike
  private windowCount = 0
  private lastExit: AppserverExitInfo | null = null
  private lastLifecycle: ProcessLifecycleEvent | null = null
  private recoveryRequired = false
  private startFailures = 0

  constructor(manager: AppserverLike = new AppServerManager()) {
    super()
    this.manager = manager
    this.manager.on('exit', (exit) => {
      this.lastExit = exit as AppserverExitInfo
      this.emit('exit', this.lastExit)
      this.emit('snapshot', this.snapshot())
    })
    this.manager.on('error', () => {
      this.startFailures += 1
      this.emit('snapshot', this.snapshot())
    })
    this.manager.on('status', () => {
      this.emit('snapshot', this.snapshot())
    })
    this.manager.on('message', (message) => {
      this.noteProtocolMessage(message)
    })
  }

  snapshot(): SupervisorSnapshot {
    return {
      status: this.manager.status,
      pid: this.manager.pid,
      windowCount: this.windowCount,
      lastExit: this.lastExit,
      lastLifecycle: this.lastLifecycle,
      recoveryRequired: this.recoveryRequired,
      startFailures: this.startFailures
    }
  }

  openWindow(): SupervisorSnapshot {
    this.windowCount += 1
    this.emit('snapshot', this.snapshot())
    return this.snapshot()
  }

  closeWindow(): SupervisorSnapshot {
    if (this.windowCount > 0) this.windowCount -= 1
    if (this.windowCount === 0) {
      this.manager.kill()
    }
    this.emit('snapshot', this.snapshot())
    return this.snapshot()
  }

  start(): boolean {
    const started = this.manager.start()
    if (!started && this.manager.status === 'crashed') {
      this.startFailures += 1
    }
    return started
  }

  async stop(): Promise<void> {
    await this.manager.stop()
  }

  async restart(): Promise<SupervisorSnapshot> {
    await this.manager.stop()
    this.manager.start()
    this.emit('snapshot', this.snapshot())
    return this.snapshot()
  }

  noteProtocolMessage(message: unknown): ProcessLifecycleEvent | null {
    const event = lifecycleFromProtocolMessage(message)
    if (event === null) return null
    this.lastLifecycle = event
    if (event.method === 'event/recovery_required') {
      this.recoveryRequired = true
    }
    if (event.method === 'event/process_started') {
      this.recoveryRequired = Boolean(event.params.recovery_required)
    }
    this.emit('lifecycle', event)
    this.emit('snapshot', this.snapshot())
    return event
  }
}

let shared: ProcessSupervisor | null = null

/** Multi-window policy: one supervisor / one appserver per Desktop process. */
export function getSharedSupervisor(factory?: () => ProcessSupervisor): ProcessSupervisor {
  if (shared === null) {
    shared = factory ? factory() : new ProcessSupervisor()
  }
  return shared
}

export function resetSharedSupervisor(): void {
  shared = null
}
