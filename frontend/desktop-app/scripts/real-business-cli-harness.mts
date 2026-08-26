#!/usr/bin/env node
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync
} from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { ProtocolClient } from '@rxycode/protocol-client'
import { repositoryDir, type CleanupProof } from './cdp-harness.mts'

const REAL_BUSINESS_MODEL_ID = 'opencode-go/mimo-v2.5'
const REAL_BUSINESS_PROVIDER = 'opencode-go'
const REAL_BUSINESS_GATEWAY = 'https://opencode.ai/zen/go/v1'

function sha256(path: string): string | null {
  if (!existsSync(path)) return null
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function copyIsolatedConfiguration(targetDataDir: string): Record<string, string | null> {
  const sourceDataDir = resolve(process.env.RXYCODE_SOURCE_DATA_DIR ?? join(homedir(), '.RxyCode'))
  const hashes: Record<string, string | null> = {}
  for (const name of ['config.yaml', 'credentials.yaml']) {
    const source = join(sourceDataDir, name)
    hashes[source] = sha256(source)
    if (existsSync(source)) copyFileSync(source, join(targetDataDir, name))
  }
  return hashes
}

function sourceConfigurationUnchanged(hashes: Record<string, string | null>): boolean {
  return Object.entries(hashes).every(([path, before]) => sha256(path) === before)
}

function directoryFingerprint(root: string): string | null {
  if (!existsSync(root)) return null
  const files: string[] = []
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) walk(path)
      else files.push(path)
    }
  }
  walk(root)
  const hash = createHash('sha256')
  for (const path of files.sort()) hash.update(path).update(readFileSync(path))
  return hash.digest('hex')
}

function processExists(pid: number): boolean {
  if (pid <= 0) return false
  if (process.platform === 'win32') {
    const result = spawnSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], {
      encoding: 'utf8',
      windowsHide: true
    })
    return result.stdout.includes(`"${pid}"`)
  }
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function killProcessTree(pid: number): void {
  if (pid <= 0) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore'
    })
    return
  }
  try { process.kill(-pid, 'SIGKILL') } catch {
    try { process.kill(pid, 'SIGKILL') } catch {}
  }
}

export interface CliPromptResult {
  status: string
  text: string
  sentAt: number
  visibleFeedbackMs: number
}

export class CliAppserverHarness {
  readonly artifactDir: string
  readonly tempRoot: string
  readonly dataDir: string
  readonly workspaceDir: string
  readonly skillDir: string
  readonly protocolLines: string[] = []
  readonly approvals: string[] = []
  private readonly approvedActions = new Set<string>()
  readonly stderr: Array<{ at_ms: number; line: string }> = []
  readonly extraEnv: NodeJS.ProcessEnv
  private readonly sourceHashes: Record<string, string | null>
  private readonly sourceSkillRoot: string
  private readonly sourceSkillHash: string | null
  private readonly startedAt = Date.now()
  private child: ChildProcessWithoutNullStreams | null = null
  private client: ProtocolClient | null = null
  private stdoutBuffer = ''

  constructor(options: { artifactDir: string; extraEnv?: NodeJS.ProcessEnv }) {
    this.artifactDir = resolve(options.artifactDir)
    this.extraEnv = options.extraEnv ?? {}
    mkdirSync(this.artifactDir, { recursive: true })
    this.tempRoot = mkdtempSync(join(tmpdir(), 'rxycode-cli-real-'))
    this.dataDir = join(this.tempRoot, 'rxycode-data')
    this.workspaceDir = join(this.tempRoot, 'workspace')
    this.skillDir = join(this.tempRoot, 'skills')
    mkdirSync(this.dataDir, { recursive: true })
    mkdirSync(this.workspaceDir, { recursive: true })
    mkdirSync(this.skillDir, { recursive: true })
    this.sourceHashes = copyIsolatedConfiguration(this.dataDir)
    this.sourceSkillRoot = resolve(
      process.env.RXYCODE_TEST_SKILL_SOURCE ??
        join(homedir(), '.codex', 'skills', 'ui-ux-pro-max')
    )
    this.sourceSkillHash = directoryFingerprint(this.sourceSkillRoot)
    if (this.sourceSkillHash !== null) {
      cpSync(this.sourceSkillRoot, join(this.skillDir, 'ui-ux-pro-max'), { recursive: true })
    }
  }

  private record(message: Record<string, unknown>): void {
    const stored: Record<string, unknown> = { ...message, __at_ms: Date.now() }
    this.protocolLines.push(JSON.stringify(stored))
  }

  async start(): Promise<void> {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.extraEnv,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONPATH: repositoryDir,
      RXYCODE_REPO_DIR: repositoryDir,
      RXYCODE_DATA_DIR: this.dataDir,
      RXYCODE_V2_CONFIG_DIR: this.dataDir,
      RXYCODE_SKILLS_DIR: this.skillDir,
      RXYCODE_SKILLS_DIRS: this.skillDir
    }
    delete env.RXYCODE_APPSERVER_STUB
    this.child = spawn('python', ['-m', 'appserver'], {
      cwd: repositoryDir,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    })
    const child = this.child
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    this.client = new ProtocolClient((line) => {
      child.stdin.write(`${line}\n`)
    })
    this.client.onNotification = (method, params) => {
      this.record({ jsonrpc: '2.0', method, params })
    }
    this.client.onServerRequest = async (method, params) => {
      this.record({ jsonrpc: '2.0', method, params })
      if (method === 'approval/request') {
        const request = params as { request_id?: string; action?: string; risk_level?: string }
        const action = String(request.action ?? 'unknown')
        if (!this.approvedActions.has(action)) {
          this.approvedActions.add(action)
          this.approvals.push(`always-allow ${action} (${String(request.risk_level ?? '')})`)
        }
        return { request_id: request.request_id, decision: 'approved' }
      }
      if (method === 'question/request') {
        const request = params as { question_id?: string }
        return { question_id: request.question_id, cancelled: true }
      }
      throw new Error(`unsupported server request: ${method}`)
    }
    child.stdout.on('data', (chunk: string) => {
      this.stdoutBuffer += chunk
      const lines = this.stdoutBuffer.split(/\r?\n/)
      this.stdoutBuffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.trim() === '') continue
        void this.client?.handleLine(line)
      }
    })
    child.stderr.on('data', (chunk: string) => {
      for (const line of chunk.split(/\r?\n/).filter(Boolean)) {
        this.stderr.push({ at_ms: Date.now() - this.startedAt, line })
      }
    })
    child.once('exit', () => {
      this.client?.rejectAllPending(new Error('appserver exited'))
    })
    await this.client.requestWithTimeout('initialize', {
      client_name: 'rxycode-cli-real-e2e',
      client_version: '0.0.0-test',
      protocol_version: '1.1.0',
      capabilities: {}
    }, 30_000)
  }

  async selectOpenCodeGoModel(): Promise<{ model: string; gateway: string }> {
    if (this.client === null) throw new Error('CLI appserver is not started')
    const activated = await this.client.requestWithTimeout<{ ok?: boolean; id?: string }>(
      'models/set_active',
      { id: REAL_BUSINESS_MODEL_ID },
      30_000
    )
    if (activated?.ok !== true) {
      throw new Error(`models/set_active failed for ${REAL_BUSINESS_MODEL_ID}`)
    }
    const listed = await this.client.requestWithTimeout<{ models?: Array<Record<string, unknown>> }>(
      'models/list',
      {},
      30_000
    )
    const entry = listed.models?.find((item) => item.id === REAL_BUSINESS_MODEL_ID)
    const gateway = typeof entry?.base_url === 'string' ? String(entry.base_url).replace(/\/$/, '') : ''
    if (entry?.provider_id !== REAL_BUSINESS_PROVIDER || gateway !== REAL_BUSINESS_GATEWAY) {
      throw new Error(
        `OpenCode Go selection did not resolve to ${REAL_BUSINESS_PROVIDER}/${REAL_BUSINESS_GATEWAY} ` +
        `(provider=${String(entry?.provider_id ?? 'missing')}, gateway=${gateway || 'missing'})`
      )
    }
    return { model: REAL_BUSINESS_MODEL_ID, gateway }
  }

  async createSession(modelId: string): Promise<string> {
    if (this.client === null) throw new Error('CLI appserver is not started')
    const created = await this.client.requestWithTimeout<{ session_id: string }>(
      'session/new',
      {
        workspace_root: this.workspaceDir,
        model: modelId,
        provider_id: REAL_BUSINESS_PROVIDER
      },
      30_000
    )
    await this.client.requestWithTimeout(
      'session/set_model',
      { session_id: created.session_id, model_id: modelId },
      180_000
    ).catch(() => undefined)
    await this.client.requestWithTimeout(
      'session/warm',
      { session_id: created.session_id, timeout_seconds: 180 },
      200_000
    )
    return created.session_id
  }

  async prompt(
    sessionId: string,
    text: string,
    timeoutMs: number,
    permissionMode: 'auto_edit' | 'full_auto' = 'auto_edit'
  ): Promise<CliPromptResult> {
    if (this.client === null) throw new Error('CLI appserver is not started')
    const sentAt = Date.now()
    const beforeCount = this.protocolLines.length
    const result = await this.client.requestWithTimeout<{ status?: string; text?: string }>(
      'session/prompt',
      {
        session_id: sessionId,
        text,
        mode: 'build',
        permission_mode: permissionMode,
        timeout_seconds: Math.max(1, Math.ceil(timeoutMs / 1000))
      },
      timeoutMs + 30_000
    )
    const firstAfter = this.protocolLines.slice(beforeCount).find((line) => {
      try {
        const message = JSON.parse(line) as { method?: string }
        return String(message.method ?? '').startsWith('event/')
      } catch {
        return false
      }
    })
    const firstAt = firstAfter === undefined ? Date.now() : Number(JSON.parse(firstAfter).__at_ms ?? Date.now())
    return {
      status: String(result.status ?? 'unknown'),
      text: String(result.text ?? ''),
      sentAt,
      visibleFeedbackMs: Math.max(0, firstAt - sentAt)
    }
  }

  async interrupt(sessionId: string): Promise<void> {
    if (this.client === null) return
    try {
      await this.client.requestWithTimeout('session/interrupt', { session_id: sessionId }, 10_000)
    } catch {
      // Best-effort stop before cleanup.
    }
  }

  async cleanup(): Promise<CleanupProof> {
    const pid = this.child?.pid ?? -1
    if (this.client !== null) {
      try {
        await this.client.requestWithTimeout('shutdown', { reason: 'cli real-business teardown' }, 5_000)
      } catch {}
      this.client.rejectAllPending(new Error('cli harness cleanup'))
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 400))
    killProcessTree(pid)
    const appserverGone = pid <= 0 || !processExists(pid)
    let tempRemoved = false
    try {
      rmSync(this.tempRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
      tempRemoved = !existsSync(this.tempRoot)
    } catch {
      tempRemoved = false
    }
    const proof: CleanupProof = {
      websocket_closed: true,
      pending_cdp_requests: 0,
      electron_pid: -1,
      electron_process_gone: true,
      appserver_pid: pid > 0 ? pid : null,
      appserver_process_gone: appserverGone,
      workspace_worktree_removed: true,
      debug_port: 0,
      debug_port_closed: true,
      temp_root_removed: tempRemoved,
      source_config_unchanged: sourceConfigurationUnchanged(this.sourceHashes),
      source_skills_unchanged: directoryFingerprint(this.sourceSkillRoot) === this.sourceSkillHash,
      lease_count: 0,
      pending_rpc_count: 0,
      passed: false
    }
    proof.passed =
      proof.websocket_closed &&
      proof.pending_cdp_requests === 0 &&
      proof.electron_process_gone &&
      proof.appserver_process_gone &&
      proof.workspace_worktree_removed &&
      proof.debug_port_closed &&
      proof.temp_root_removed &&
      proof.source_config_unchanged &&
      proof.source_skills_unchanged &&
      proof.lease_count === 0 &&
      proof.pending_rpc_count === 0
    return proof
  }
}
