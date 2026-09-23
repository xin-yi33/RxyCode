/**
 * PhaseG-H7: Tool/Command/BackgroundTask workbench projection + redaction.
 */

export type ExecStatus =
  | 'running'
  | 'ok'
  | 'failed'
  | 'cancelled'
  | 'timed_out'
  | 'approval'

export interface ExecItem {
  id: string
  name: string
  argsSummary: string
  risk: 'READ' | 'WRITE' | 'DANGER'
  cwd: string
  exitCode: number | null
  stdout: string
  stderr: string
  truncated: boolean
  status: ExecStatus
}

export function redactSecrets(text: string): string {
  return text
    .replace(/api[_-]?key\s*[:=]\s*\S+/gi, 'api_key=[REDACTED]')
    .replace(/bearer\s+\S+/gi, 'Bearer [REDACTED]')
    .replace(/authorization\s*[:=]\s*\S+/gi, 'authorization=[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]+\b/g, '[REDACTED]')
}

export function redactPath(cwd: string, homeHint = ''): string {
  const normCwd = cwd.replace(/\\/g, '/')
  const normHome = homeHint.replace(/\\/g, '/')
  if (normHome !== '' && (normCwd === normHome || normCwd.startsWith(`${normHome}/`))) {
    return `~${normCwd.slice(normHome.length)}`
  }
  return cwd
}

export function projectExecItem(raw: {
  id: string
  name: string
  argsSummary?: string
  risk?: ExecItem['risk']
  cwd?: string
  exitCode?: number | null
  stdout?: string
  stderr?: string
  truncated?: boolean
  status: ExecStatus
  homeHint?: string
}): ExecItem {
  return {
    id: raw.id,
    name: raw.name,
    argsSummary: redactSecrets(raw.argsSummary ?? ''),
    risk: raw.risk ?? 'READ',
    cwd: redactPath(raw.cwd ?? '', raw.homeHint ?? ''),
    exitCode: raw.exitCode ?? null,
    stdout: redactSecrets(raw.stdout ?? ''),
    stderr: redactSecrets(raw.stderr ?? ''),
    truncated: raw.truncated === true,
    status: raw.status
  }
}

const TRANSITIONS: Record<ExecStatus, ExecStatus[]> = {
  running: ['ok', 'failed', 'cancelled', 'timed_out', 'approval'],
  approval: ['running', 'cancelled', 'failed'],
  ok: [],
  failed: [],
  cancelled: [],
  timed_out: []
}

export function canTransition(from: ExecStatus, to: ExecStatus): boolean {
  return TRANSITIONS[from].includes(to)
}

export function isSuccess(item: ExecItem): boolean {
  return item.status === 'ok'
}
