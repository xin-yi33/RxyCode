/**
 * AppServer process manager for the Electron main process (Phase4-D1).
 *
 * Owns the `python -m appserver` child process: spawn, raw stdio line
 * forwarding, graceful stop (stdin EOF) and kill-on-quit so a Desktop
 * crash cannot leave an orphaned appserver (DC5).
 *
 * Constraint: this module never imports Python and never talks HTTP.
 * JSON-RPC is owned by the renderer's ProtocolClient; this manager only
 * moves raw newline-delimited lines and never builds its own request ids.
 */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { findBundledRuntime, type BundledRuntime } from './runtime.ts'

export type AppserverStatus = 'stopped' | 'starting' | 'running' | 'crashed'

export interface AppServerManagerOptions {
  /** Directory used to resolve the repository root. */
  cwd?: string
  /** Bundled runtime override; defaults to resources/runtime resolution. */
  runtime?: BundledRuntime | null
  /** Python executable; defaults to `python`. */
  python?: string
  /** Run appserver with RXYCODE_APPSERVER_STUB=1 (deterministic, no LLM). */
  stub?: boolean
  /** Run the in-repo fake appserver script instead of Python (UI demos). */
  fakeAppserver?: boolean
  /** Spawn the orphan guard (job object on Windows, group guard on POSIX). */
  guard?: boolean
  /** Test hook: skip repo/runtime discovery and spawn this spec. */
  spawnOverride?: SpawnSpec
}

export interface AppserverExitInfo {
  code: number | null
  signal: NodeJS.Signals | null
}

const SHUTDOWN_TIMEOUT_MS = 5_000
const KILL_WAIT_TIMEOUT_MS = 3_000
const MAX_LOG_LINES = 200

/**
 * Force-kill a process and its whole descendant tree.
 *
 * Windows uses taskkill /T /F (tree kill). POSIX uses the process group
 * (the child is spawned with detached:true, so it leads its own group).
 */
export function killProcessTree(pid: number): Promise<void> {
  return new Promise((resolveKill) => {
    if (process.platform === 'win32') {
      const killer = spawn('taskkill', ['/pid', String(pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true
      })
      killer.once('exit', () => resolveKill())
      killer.once('error', () => resolveKill())
    } else {
      try {
        process.kill(-pid, 'SIGKILL')
      } catch {
        try {
          process.kill(pid, 'SIGKILL')
        } catch {
          // already gone
        }
      }
      resolveKill()
    }
  })
}

export function findRepoRoot(startDir: string = process.cwd()): string {
  const candidates: string[] = []
  const fromEnv = process.env.RXYCODE_REPO_DIR
  if (fromEnv) {
    candidates.push(resolve(fromEnv))
  }
  let current = resolve(startDir)
  for (let depth = 0; depth < 20; depth += 1) {
    candidates.push(current)
    const parent = resolve(current, '..')
    if (parent === current) break
    current = parent
  }
  // Desktop repo layout: RxyCode-Desktop sits beside RxyCode-master.
  candidates.push(resolve(startDir, '..', 'RxyCode-master'))
  for (const candidate of candidates) {
    if (existsSync(join(candidate, 'appserver', '__main__.py'))) {
      return candidate
    }
  }
  throw new Error(
    `repository root not found (appserver/__main__.py) from ${startDir}; set RXYCODE_REPO_DIR if the RxyCode repo lives elsewhere`
  )
}

export interface SpawnSpec {
  command: string
  args: string[]
  cwd: string
  env: NodeJS.ProcessEnv
  detached: boolean
}

/**
 * Decide how to spawn the appserver process (Phase4-D6).
 *
 * Priority: bundled runtime (packaged app) > dev python on PATH with the
 * repository root as cwd. The fake appserver script is a UI demo mode.
 */
export function buildSpawnSpec(options: {
  fakeAppserver?: boolean
  python?: string
  stub?: boolean
  runtime?: BundledRuntime | null
  repoRoot: string | null
  scriptsDir?: string
}): SpawnSpec {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8'
  }
  if (options.stub) env.RXYCODE_APPSERVER_STUB = '1'
  if (options.fakeAppserver) {
    env.ELECTRON_RUN_AS_NODE = '1'
    const scriptsDir = options.scriptsDir ?? join(__dirname, '..', '..', 'scripts')
    return {
      command: process.execPath,
      args: [join(scriptsDir, 'fake-appserver.mjs')],
      cwd: options.repoRoot ?? process.cwd(),
      env,
      detached: process.platform !== 'win32'
    }
  }
  env.RXYCODE_APPSERVER_PREEMPT = '1'
  if (options.runtime !== null && options.runtime !== undefined) {
    return {
      command: options.runtime.python,
      args: ['-m', 'appserver'],
      cwd: options.runtime.appDir,
      env,
      detached: process.platform !== 'win32'
    }
  }
  if (options.repoRoot === null) {
    throw new Error(
      'appserver start requires a bundled runtime or a repository root; set RXYCODE_REPO_DIR if the RxyCode repo lives elsewhere'
    )
  }
  return {
    command: options.python ?? 'python',
    args: ['-m', 'appserver'],
    cwd: options.repoRoot,
    env,
    detached: process.platform !== 'win32'
  }
}

/**
 * Map a scripts path inside app.asar to its asar.unpacked sibling so a
 * child process (powershell/node) can read the file, or return null when
 * the script is not available on disk.
 */
function onDiskScriptPath(script: string): string | null {
  const unpacked = script.replace(/app\.asar(?=\/|\\)/, 'app.asar.unpacked')
  if (existsSync(unpacked)) return unpacked
  return null
}

export class AppServerManager extends EventEmitter {
  readonly protocolViolations: string[] = []
  private readonly options: AppServerManagerOptions
  private readonly devRepoRoot: string | null
  private child: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ''
  private lastLogs: string[] = []
  startedAt: number | null = null
  lastExit: AppserverExitInfo | null = null
  status: AppserverStatus = 'stopped'

  constructor(options: AppServerManagerOptions = {}) {
    super()
    this.on('error', () => {})
    this.options = options
    let devRoot: string | null = null
    try {
      devRoot = findRepoRoot(options.cwd)
    } catch {
      devRoot = null
    }
    this.devRepoRoot = devRoot
  }

  /** Bundled runtime from options, or resolved from `resources/runtime`. */
  private bundledRuntime(): BundledRuntime | null {
    return this.options.runtime === undefined
      ? findBundledRuntime(process.resourcesPath)
      : this.options.runtime
  }

  get pid(): number | null {
    return this.child?.pid ?? null
  }

  get repoRootDir(): string {
    return this.bundledRuntime()?.appDir ?? this.devRepoRoot ?? ''
  }

  /** Which appserver source is in use: bundled runtime, dev python, or fake. */
  get runtimeLabel(): 'bundled' | 'dev' | 'fake' {
    if (this.options.fakeAppserver) return 'fake'
    if (this.bundledRuntime() !== null) return 'bundled'
    return 'dev'
  }

  get logs(): readonly string[] {
    return this.lastLogs
  }

  start(): boolean {
    if (this.child !== null) return false
    this.status = 'starting'
    this.emit('status', this.status)

    const spec = this.options.spawnOverride ?? (() => {
      const runtime = this.bundledRuntime()
      const repoRoot = runtime !== null ? null : this.devRepoRoot
      return buildSpawnSpec({
        fakeAppserver: this.options.fakeAppserver,
        python: this.options.python,
        stub: this.options.stub,
        runtime,
        repoRoot
      })
    })()

    const child = spawn(spec.command, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      stdio: ['pipe', 'pipe', 'pipe'],
      detached: spec.detached,
      windowsHide: true
    })
    this.child = child
    if (child.pid !== undefined && this.options.guard !== false) {
      this.startOrphanGuard(child.pid)
    }
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.handleStdout(chunk))
    child.stderr.on('data', (chunk: string) => this.handleStderr(chunk))
    child.on('spawn', () => {
      if (this.child !== child) return
      this.startedAt = Date.now()
      this.status = 'running'
      this.emit('status', this.status)
    })
    child.on('error', (error) => {
      if (this.child === child) this.child = null
      this.startedAt = null
      this.status = 'crashed'
      this.emit('status', this.status)
      this.emit('error', error)
    })
    child.on('exit', (code, signal) => {
      if (this.child === child) this.child = null
      const exit = { code, signal } as AppserverExitInfo
      this.lastExit = exit
      this.startedAt = null
      this.status = code === 0 ? 'stopped' : 'crashed'
      this.emit('status', this.status)
      this.emit('exit', exit)
    })
    return true
  }

  /**
   * Wait until status is running, or fail on crash/timeout.
   * AbortSignal cancels the wait (does not kill unless timeout fires).
   */
  waitUntilRunning(timeoutMs = 15_000, signal?: AbortSignal): Promise<void> {
    if (this.status === 'running') return Promise.resolve()
    if (this.status === 'crashed') {
      return Promise.reject(new Error('appserver crashed during start'))
    }
    return new Promise((resolve, reject) => {
      let done = false
      const finish = (error?: Error): void => {
        if (done) return
        done = true
        this.off('status', onStatus)
        this.off('error', onError)
        clearTimeout(timer)
        signal?.removeEventListener('abort', onAbort)
        if (error) reject(error)
        else resolve()
      }
      const onStatus = (status: AppserverStatus): void => {
        if (status === 'running') finish()
        if (status === 'crashed') finish(new Error('appserver crashed during start'))
      }
      const onError = (error: Error): void => {
        finish(error)
      }
      const onAbort = (): void => {
        finish(new Error('appserver start cancelled'))
      }
      const timer = setTimeout(() => {
        if (this.pid !== null) void killProcessTree(this.pid)
        finish(new Error(`appserver start timed out after ${timeoutMs}ms`))
      }, timeoutMs)
      this.on('status', onStatus)
      this.on('error', onError)
      signal?.addEventListener('abort', onAbort, { once: true })
    })
  }

  /**
   * Hard-crash orphan protection (DC5).
   *
   * Windows: a PowerShell helper assigns the appserver to a Job Object
   * with KILL_ON_JOB_CLOSE. When Electron dies (even taskkill /T) the
   * helper dies too, the job handle closes and Windows kills the whole
   * appserver tree.
   *
   * POSIX: a detached node guard watches the parent pid and SIGKILLs the
   * appserver process group when the parent disappears.
   */
  private startOrphanGuard(childPid: number): void {
    const scriptsDir = join(__dirname, '..', '..', 'scripts')
    if (process.platform === 'win32') {
      const script = onDiskScriptPath(join(scriptsDir, 'win-job-guard.ps1'))
      if (script === null) return
      const guard = spawn(
        'powershell.exe',
        [
          '-NoProfile',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          script,
          '-ParentPid',
          String(process.pid),
          '-ChildPid',
          String(childPid)
        ],
        { stdio: 'ignore', windowsHide: true }
      )
      guard.unref()
    } else {
      const script = onDiskScriptPath(join(scriptsDir, 'orphan-guard.mjs'))
      if (script === null) return
      const guard = spawn(process.execPath, [script, String(process.pid), String(childPid)], {
        stdio: 'ignore',
        detached: true
      })
      guard.unref()
    }
  }

  /** Raw line bridge for the renderer's ProtocolClient (Phase4-D2). */
  sendLine(line: string): void {
    if (this.child === null) return
    this.writeLine(line)
  }

  async stop(): Promise<void> {
    const child = this.child
    if (child === null || child.exitCode !== null || child.signalCode !== null) return
    const exited = new Promise<void>((resolveExit) => {
      child.once('exit', () => resolveExit())
    })
    // EOF on stdin makes the appserver break its read loop and shut down
    // gracefully. No JSON-RPC shutdown request is sent from here, so the
    // renderer's ProtocolClient stays the sole owner of the id space.
    child.stdin.end()
    const stillRunning = await Promise.race([
      exited.then(() => false),
      new Promise<boolean>((resolveTimer) => {
        setTimeout(() => resolveTimer(true), SHUTDOWN_TIMEOUT_MS)
      })
    ])
    if (stillRunning && this.child === child && child.pid !== undefined) {
      await killProcessTree(child.pid)
    }
    await Promise.race([
      exited,
      new Promise<void>((resolveTimer) => {
        setTimeout(resolveTimer, KILL_WAIT_TIMEOUT_MS)
      })
    ])
  }

  kill(): void {
    const child = this.child
    if (child !== null && child.pid !== undefined) void killProcessTree(child.pid)
  }

  private writeLine(line: string): void {
    if (this.child === null || this.child.stdin.writableEnded) return
    this.child?.stdin.write(`${line}\n`)
  }

  private handleStdout(chunk: string): void {
    this.stdoutBuffer += chunk
    const lines = this.stdoutBuffer.split(/\r?\n/)
    this.stdoutBuffer = lines.pop() ?? ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (trimmed === '') continue
      this.emit('line', trimmed)
      let message: unknown
      try {
        message = JSON.parse(trimmed)
      } catch {
        this.protocolViolations.push(trimmed)
        this.emit('protocol-error', trimmed)
        continue
      }
      this.handleProtocolMessage(message)
    }
  }

  private handleProtocolMessage(message: unknown): void {
    this.emit('message', message)
  }

  private handleStderr(chunk: string): void {
    for (const line of chunk.split(/\r?\n/)) {
      const trimmed = line.trim()
      if (trimmed === '') continue
      this.lastLogs.push(trimmed)
      if (this.lastLogs.length > MAX_LOG_LINES) this.lastLogs.shift()
      this.emit('log', trimmed)
    }
  }
}
