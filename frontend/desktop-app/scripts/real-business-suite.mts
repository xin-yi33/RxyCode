#!/usr/bin/env node
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve, basename } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DesktopCdpHarness, desktopAppDir, repositoryDir, selectRendererTarget, waitFor, type CleanupProof } from './cdp-harness.mts'
import { CliAppserverHarness } from './real-business-cli-harness.mts'
import { buildBatchPrompts, buildMissingFileRepairPrompt, buildSpringMysqlRepairInstructions, selectMissingFileRepair, realBusinessScenarios, type RealBusinessScenario } from './real-business-scenarios.mts'
import {
  aggregateUsage,
  evaluateLayoutSnapshot,
  gameMenuStillBlockingPlay,
  isMeaningfulProtocolEvent,
  missingWebDeliverables,
  parseDotEnv,
  mysqlPartsFromJdbc,
  companyLoginProbeIssue,
  companyWebsiteArtifactIssue,
  travelWebsiteArtifactIssue,
  marketBiArtifactIssue,
  evTcoArtifactIssue,
  rentalDecisionArtifactIssue,
  springMysqlArtifactIssue,
  findProjectLocalMaven,
  mavenTestCountsIssue,
  missingOutputDirIssue,
  webServeRoot,
  terminalOutcomeIssue,
  hasInFlightTool,
  hasInFlightRecovery,
  selectJavaSwingMain,
  firstTokenHardFail,
  approvalStormIssue,
  taskWallClockIssue,
  scenariosFrom,
  type UsageSample,
  type UsageSummary
} from './real-business-metrics.mts'

/** Hung bash (python http.server / Stop-Process) must not wait out the scenario wall clock. Maven tests may run longer than 30s, so in-flight tools get a longer stall budget. */
const IN_FLIGHT_TOOL_STALL_MS = 180_000

const PROTOCOL_CAPTURE_BOOTSTRAP = `(() => {
  window.__rxyRealProtocol = [];
  window.__rxyCdAppserverLogs = [];
  window.__rxyWatchdog = {
    firstActivityAt: null,
    lastVisibleAt: Date.now(),
    inFlightTools: 0,
    pendingToolPrep: false,
    recoveryOpen: false
  };
  const waiting = /waiting for model response|build in progress|\\u6b63\\u5728\\u7b49\\u5f85\\u6a21\\u578b\\u54cd\\u5e94/i;
  const preparingTool = /preparing write tool call/i;
  const activity = new Set(['event/message_delta', 'event/tool_begin', 'event/tool_end', 'event/progress', 'event/plan', 'event/step', 'event/recovery_started', 'event/recovery_attempt']);
  const visible = new Set(['event/message_delta', 'event/tool_begin', 'event/tool_end', 'event/progress', 'event/plan', 'event/step', 'event/error', 'event/final', 'event/recovery_started', 'event/recovery_attempt', 'event/recovery_resolved', 'event/recovery_exhausted']);
  window.api.appserver.onLog((line) => window.__rxyCdAppserverLogs.push(String(line)));
  window.api.appserver.onLine((line) => {
    try {
      const message = JSON.parse(line);
      message.__at_ms = Date.now();
      const method = String(message.method || '');
      const callId = String(message.params?.call_id || '');
      const text = String(message.params?.text || '');
      const watchdog = window.__rxyWatchdog;
      if (method === 'event/tool_begin' && callId) {
        watchdog.inFlightTools += 1;
        watchdog.pendingToolPrep = false;
      }
      if (method === 'event/tool_end' && callId && watchdog.inFlightTools > 0) watchdog.inFlightTools -= 1;
      if (method === 'event/final') watchdog.pendingToolPrep = false;
      if (method === 'event/progress' && preparingTool.test(text)) watchdog.pendingToolPrep = true;
      if (method === 'event/recovery_started' || method === 'event/recovery_attempt') watchdog.recoveryOpen = true;
      if (method === 'event/recovery_resolved' || method === 'event/recovery_exhausted') watchdog.recoveryOpen = false;
      const waitingProgress = method === 'event/progress' && waiting.test(text);
      if (activity.has(method) && !waitingProgress && watchdog.firstActivityAt == null) watchdog.firstActivityAt = message.__at_ms;
      if ((visible.has(method) && !waitingProgress) || method === 'approval/request' || method === 'approval/decision') {
        watchdog.lastVisibleAt = message.__at_ms;
      }
      const stored = message.params ? { ...message, params: { ...message.params } } : message;
      if (stored.params && stored.params.summary && String(stored.params.summary).length > 4000) {
        stored.params.summary = String(stored.params.summary).slice(0, 4000) + '\u2026';
      }
      if (stored.params && stored.params.arguments != null) {
        const raw = JSON.stringify(stored.params.arguments);
        if (raw.length > 4000) stored.params.arguments = { truncated: true, preview: raw.slice(0, 4000) };
      }
      window.__rxyRealProtocol.push(JSON.stringify(stored));
    } catch {}
  });
})()`

type Batch = 'A' | 'B'
type ProtocolMessage = Record<string, any> & { __at_ms?: number }

interface RealBusinessResult {
  id: string
  batch: Batch
  title: string
  prompt: string
  model: string
  provider: string
  gateway: string
  session_id: string
  status: string
  final_answer: string
  output_dir: string
  files: string[]
  artifact_kind: string
  usage: UsageSummary
  timing: {
    wall_ms: number
    visible_feedback_ms: number | null
    first_event_ms: number | null
    first_token_ms: number | null
    final_ms: number | null
    silent_gaps_ms: number[]
  }
  approvals: string[]
  tools: string[]
  skill_events: string[]
  mcp_events: string[]
  layout: { issues: Array<{ kind: string; elements: string[]; detail: string }> }
  layout_snapshot?: {
    viewport: { width: number; height: number }
    horizontalScroll: number
    elements: Array<{ id: string; left: number; top: number; right: number; bottom: number }>
  } | null
  screenshots: string[]
  protocol_file: string
  dom_file: string
  cleanup: CleanupProof | null
  defects: string[]
  repair_attempts: string[]
  error: string | null
}

function failureResult(
  scenario: RealBusinessScenario,
  batch: Batch,
  prompt: string,
  sessionId: string,
  model: string,
  gateway: string,
  batchDir: string,
  error: unknown
): RealBusinessResult {
  const message = error instanceof Error ? error.message : String(error)
  return {
    id: scenario.id,
    batch,
    title: scenario.title,
    prompt,
    model,
    provider: REAL_BUSINESS_PROVIDER,
    gateway,
    session_id: sessionId,
    status: 'failed',
    final_answer: '',
    output_dir: join(batchDir, 'outputs', scenario.outputDir),
    files: [],
    artifact_kind: scenario.artifactKind,
    usage: {
      input_tokens: null,
      output_tokens: null,
      cache_hit_tokens: null,
      cache_miss_tokens: null,
      total_tokens: null,
      reporting_status: 'not_reported'
    },
    timing: {
      wall_ms: 0,
      visible_feedback_ms: null,
      first_event_ms: null,
      first_token_ms: null,
      final_ms: null,
      silent_gaps_ms: []
    },
    approvals: [],
    tools: [],
    skill_events: [],
    mcp_events: [],
    layout: { issues: [] },
    layout_snapshot: null,
    screenshots: [],
    protocol_file: join(batchDir, 'events', `${scenario.id}.ndjson`),
    dom_file: join(batchDir, 'dom', `${scenario.id}.json`),
    cleanup: null,
    defects: ['scenario runner exception prevented complete evidence collection'],
    repair_attempts: [],
    error: message
  }
}

const scriptDir = dirname(fileURLToPath(import.meta.url))
const defaultArtifactRoot = resolve(scriptDir, '..', '..', '..', 'artifacts')
const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
const artifactRoot = resolve(
  process.argv.find((arg) => arg.startsWith('--artifacts='))?.slice('--artifacts='.length) ??
    join(defaultArtifactRoot, `rxycode-gui-real-e2e-${timestamp}`)
)
const only = new Set((process.argv.find((arg) => arg.startsWith('--only='))?.slice('--only='.length) ?? '').split(',').filter(Boolean))
const fromId = process.argv.find((arg) => arg.startsWith('--from='))?.slice('--from='.length)
const batchArg = (process.argv.find((arg) => arg.startsWith('--batch='))?.slice('--batch='.length) ?? 'both').toUpperCase()
const batches: Batch[] = batchArg === 'A' || batchArg === 'B' ? [batchArg as Batch] : ['A', 'B']
const surfaceArg = (process.argv.find((arg) => arg.startsWith('--surface='))?.slice('--surface='.length) ?? 'gui').toLowerCase()
const surface: 'gui' | 'cli' = surfaceArg === 'cli' ? 'cli' : 'gui'
const selected = scenariosFrom(
  realBusinessScenarios.filter((scenario) => only.size === 0 || only.has(scenario.id)),
  fromId
)
const prompts = buildBatchPrompts()
const REAL_BUSINESS_MODEL_ID = 'opencode-go/mimo-v2.5'
const REAL_BUSINESS_PROVIDER = 'opencode-go'
const REAL_BUSINESS_GATEWAY = 'https://opencode.ai/zen/go/v1'

function mysqlTestEnv(): Record<string, string> {
  const envPath = join(repositoryDir, '.env.t09-mysql')
  if (!existsSync(envPath)) return {}
  const parsed = parseDotEnv(readFileSync(envPath, 'utf8'))
  const allowed = [
    'MYSQL_URL',
    'MYSQL_USER',
    'MYSQL_PASSWORD',
    'MYSQL_ADMIN_PASSWORD',
    'SPRING_DATASOURCE_URL',
    'SPRING_DATASOURCE_USERNAME',
    'SPRING_DATASOURCE_PASSWORD',
    'APP_ADMIN_USERNAME',
    'APP_ADMIN_PASSWORD',
    'T09_ADMIN_PASSWORD'
  ]
  const out: Record<string, string> = {}
  for (const key of allowed) {
    const value = parsed[key]
    if (typeof value === 'string' && value.length > 0) out[key] = value
  }
  Object.assign(out, mysqlPartsFromJdbc(out.MYSQL_URL ?? out.SPRING_DATASOURCE_URL ?? ''))
  if (!out.APP_ADMIN_USERNAME) out.APP_ADMIN_USERNAME = 'admin'
  if (!out.APP_ADMIN_PASSWORD) out.APP_ADMIN_PASSWORD = out.T09_ADMIN_PASSWORD || 't09-demo-login'
  if (!out.T09_ADMIN_PASSWORD) out.T09_ADMIN_PASSWORD = out.APP_ADMIN_PASSWORD
  return out
}

function desktopSuiteEnv(): Record<string, string> {
  return {
    RXYCODE_SUBAGENTS: '1',
    RXYCODE_SUBAGENTS_TASK: '1',
    RXYCODE_SUBAGENTS_MENTION: '1',
    RXYCODE_SUBAGENTS_CHILD_TASKS: '1',
    ...mysqlTestEnv()
  }
}

function parseProtocol(lines: string[]): ProtocolMessage[] {
  return lines.flatMap((line) => {
    try { return [JSON.parse(line) as ProtocolMessage] } catch { return [] }
  })
}

function countKnownApproval(messages: ProtocolMessage[]): string[] {
  return messages.filter((message) => String(message.method ?? '').includes('approval'))
    .map((message) => String(message.method))
}

function protocolUsage(messages: ProtocolMessage[]): UsageSummary {
  const samples: UsageSample[] = messages
    .filter((message) => message.method === 'event/token_usage' || message.method === 'event/final')
    .map((message) => {
      const params = message.params ?? {}
      const input = typeof params.input_tokens === 'number' ? params.input_tokens : null
      const hit = typeof params.cache_hit_tokens === 'number' ? params.cache_hit_tokens : null
      const miss = typeof params.cache_miss_tokens === 'number'
        ? params.cache_miss_tokens
        : input !== null && hit !== null ? Math.max(0, input - hit) : null
      return {
        input_tokens: input,
        output_tokens: typeof params.output_tokens === 'number' ? params.output_tokens : null,
        cache_hit_tokens: hit,
        cache_miss_tokens: miss,
        reporting_status: params.reporting_status === 'reported' || params.reporting_status === 'partial'
          ? params.reporting_status
          : input !== null || hit !== null ? 'partial' : 'not_reported'
      }
    })
  return aggregateUsage(samples.length > 1 ? [samples.at(-1)!] : samples)
}

function getGateway(messages: ProtocolMessage[]): string {
  // JSON-RPC responses do not repeat the request method. Identify the model
  // catalog response by its result shape rather than looking for a missing
  // `method` field.
  const model = messages.findLast((message) => Array.isArray(message.result?.models))?.result
  const entry = model?.models?.find((item: any) => item.id === REAL_BUSINESS_MODEL_ID)
  return typeof entry?.base_url === 'string' ? entry.base_url.replace(/\/$/, '') : ''
}

function getSuiteModelEntry(messages: ProtocolMessage[]): Record<string, any> | null {
  const model = messages.findLast((message) => Array.isArray(message.result?.models))?.result
  const entry = model?.models?.find((item: any) => item.id === REAL_BUSINESS_MODEL_ID)
  return entry !== null && typeof entry === 'object' ? entry as Record<string, any> : null
}

function eventTiming(messages: ProtocolMessage[], startedAt: number, sessionId: string): RealBusinessResult['timing'] {
  const events = messages.filter((message) =>
    typeof message.__at_ms === 'number' &&
    Number(message.__at_ms) >= startedAt &&
    String(message.params?.session_id ?? '') === sessionId &&
    isMeaningfulProtocolEvent(message)
  )
  const eventTimes = events.map((message) => Number(message.__at_ms) - startedAt)
  const firstEvent = events.find((message) => String(message.method ?? '').startsWith('event/'))
  const firstToken = events.find((message) => {
    const method = String(message.method ?? '').toLowerCase()
    // Progress, tool summaries and reasoning snapshots are visible events but
    // are not the first answer token.  Measure the first actual assistant
    // message delta so the GUI performance gate cannot report 0ms merely
    // because the appserver announced "Analyzing your request".
    return method === 'event/message_delta'
  })
  const final = events.findLast((message) => message.method === 'event/final')
  const gaps: number[] = []
  for (let index = 1; index < eventTimes.length; index += 1) {
    const gap = eventTimes[index]! - eventTimes[index - 1]!
    const previousAt = Number(events[index - 1]!.__at_ms)
    if (gap > 10_000 && !hasInFlightTool(messages, sessionId, previousAt, Number(events[index]!.__at_ms)) && !hasInFlightRecovery(messages, sessionId, previousAt, Number(events[index]!.__at_ms))) gaps.push(gap)
  }
  const timing: RealBusinessResult['timing'] = {
    wall_ms: Math.max(0, Date.now() - startedAt),
    visible_feedback_ms: null,
    first_event_ms: firstEvent?.__at_ms === undefined ? null : Math.max(0, Number(firstEvent.__at_ms) - startedAt),
    first_token_ms: firstToken?.__at_ms === undefined ? null : Math.max(0, Number(firstToken.__at_ms) - startedAt),
    final_ms: final?.__at_ms === undefined ? null : Math.max(0, Number(final.__at_ms) - startedAt),
    silent_gaps_ms: gaps
  }
  return timing
}

function copyTree(source: string, target: string, relativeRoot = target): string[] {
  const files: string[] = []
  if (!existsSync(source)) return files
  mkdirSync(target, { recursive: true })
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'target') continue
    const from = join(source, entry.name)
    const to = join(target, entry.name)
    if (entry.isDirectory()) files.push(...copyTree(from, to, relativeRoot))
    else {
      cpSync(from, to)
      files.push(relative(relativeRoot, to))
    }
  }
  return files
}

function persistPlayProbe(source: string, batchDir: string, scenarioId: string): void {
  const destDir = join(batchDir, 'probes')
  mkdirSync(destDir, { recursive: true })
  for (const name of ['.rxy-play-probe.json', '.rxy-play-probe.png']) {
    const from = join(source, name)
    if (!existsSync(from)) continue
    cpSync(from, join(destDir, `${scenarioId}${name}`))
  }
}

function listFiles(root: string): string[] {
  const output: string[] = []
  if (!existsSync(root)) return output
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'target') continue
      const path = join(directory, entry.name)
      if (entry.isDirectory()) walk(path)
      else output.push(relative(root, path))
    }
  }
  walk(root)
  return output.sort()
}

function hasScenarioDoc(source: string, name: string): boolean {
  if (existsSync(join(source, name))) return true
  return existsSync(join(source, basename(source), name))
}

async function selectOpenCodeGoModelInSettings(harness: DesktopCdpHarness): Promise<void> {
  const modelId = REAL_BUSINESS_MODEL_ID
  await harness.waitForSelector('[data-testid="open-settings"]', 60_000)
  await harness.evaluate('document.querySelector("[data-testid=\\"open-settings\\"]")?.click()')
  await harness.waitForSelector('[data-testid="settings-dialog"]', 10_000)
  await harness.evaluate('document.querySelector("[data-tab=\\"model\\"]")?.click()')
  await waitFor(
    async () => await harness.evaluate<boolean>(`Boolean(document.querySelector('[data-testid="model-row"][data-model-id=${JSON.stringify(modelId)}]'))`) ? true : null,
    60_000,
    'OpenCode Go mimo-v2.5 in GUI model center'
  )
  const alreadyActive = await harness.evaluate<boolean>(`Boolean(document.querySelector('[data-testid="model-row"][data-model-id=${JSON.stringify(modelId)}].active'))`)
  if (!alreadyActive) {
    await harness.evaluate(`document.querySelector('[data-testid="model-row"][data-model-id=${JSON.stringify(modelId)}] [data-testid="model-activate"]')?.click()`)
    await waitFor(
      async () => await harness.evaluate<boolean>(`(() => {
        const dialog = document.querySelector('[data-testid="settings-dialog"]')
        const row = document.querySelector('[data-testid="model-row"][data-model-id=${JSON.stringify(modelId)}]')
        return dialog === null || row?.classList.contains('active')
      })()`) ? true : null,
      45_000,
      'activate OpenCode Go mimo-v2.5 in GUI'
    )
  }
  // Selecting the global default closes the settings page when there is no
  // active task. Close it explicitly as well so the next click is measured
  // from the normal task surface.
  await harness.evaluate('document.querySelector("[data-testid=\\"settings-dialog\\"] .settings-close")?.click()')
  await waitFor(async () => await harness.evaluate<boolean>('!Boolean(document.querySelector("[data-testid=\\"settings-dialog\\"]"))') ? true : null, 5_000, 'close model center after GUI selection')
}

async function createSession(harness: DesktopCdpHarness): Promise<string> {
  await waitFor(async () => {
    const state = await harness.evaluate<{ ready: boolean; status: string; error: string; button: string }>(`(() => {
      const button = document.querySelector('[data-testid="new-session"]');
      const status = document.querySelector('.connection-status')?.textContent?.trim() ?? 'unknown';
      const error = document.querySelector('.error-banner')?.textContent?.trim() ?? '';
      return {
        ready: button instanceof HTMLButtonElement && !button.disabled,
        status,
        error,
        button: button instanceof HTMLButtonElement ? String(button.disabled) : 'missing'
      };
    })()`)
    if (state.error !== '' || /crashed|stopped/i.test(state.status)) {
      throw new Error(`appserver was not ready for a new task (status=${state.status}, button=${state.button}, error=${state.error || 'none'})`)
    }
    return state.ready ? true : null
  }, 60_000, 'appserver protocol ready for new task')
  const previous = await harness.evaluate<number>('document.querySelectorAll(".session-item").length')
  await harness.evaluate(`(() => {
    const button = document.querySelector('[data-testid="new-session"]');
    if (!(button instanceof HTMLButtonElement) || button.disabled) throw new Error('new task button is not enabled after protocol readiness');
    button.click();
  })()`)
  await waitFor(async () => {
    const count = await harness.evaluate<number>('document.querySelectorAll(".session-item").length')
    return count > previous ? true : null
  }, 30_000, 'create real business task')
  return harness.evaluate<string>('document.querySelector(".session-item.active .session-id")?.textContent?.trim() ?? ""')
}

async function assertOpenCodeGoModel(harness: DesktopCdpHarness): Promise<{ model: string; gateway: string }> {
  const modelId = REAL_BUSINESS_MODEL_ID
  await harness.waitForSelector('[data-testid="composer-model"]', 60_000)
  await waitFor(async () => await harness.evaluate<boolean>(`Boolean(document.querySelector('[data-testid="composer-model"] option[value=${JSON.stringify(modelId)}]'))`) ? true : null, 60_000, 'OpenCode Go mimo-v2.5 option')
  await waitFor(async () => await harness.evaluate<boolean>(`document.querySelector('[data-testid="composer-model"]')?.value === ${JSON.stringify(modelId)}`) ? true : null, 45_000, 'apply OpenCode Go mimo-v2.5 in GUI')
  const lines = parseProtocol(await harness.evaluate<string[]>('window.__rxyRealProtocol ?? []'))
  const entry = getSuiteModelEntry(lines)
  const gateway = getGateway(lines)
  if (entry?.provider_id !== REAL_BUSINESS_PROVIDER || gateway !== REAL_BUSINESS_GATEWAY) {
    throw new Error(`OpenCode Go selection did not resolve to ${REAL_BUSINESS_PROVIDER}/${REAL_BUSINESS_GATEWAY} (provider=${String(entry?.provider_id ?? 'missing')}, gateway=${gateway || 'missing'})`)
  }
  return { model: modelId, gateway }
}

async function setPermission(harness: DesktopCdpHarness, mode: 'auto_edit' | 'full_auto'): Promise<void> {
  await harness.waitForSelector('[data-testid="composer-permission-mode"]', 10_000)
  await harness.evaluate(`(() => {
    const select = document.querySelector('[data-testid="composer-permission-mode"]');
    if (!(select instanceof HTMLSelectElement)) throw new Error('permission selector missing');
    select.value = ${JSON.stringify(mode)};
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`)
  if (mode === 'full_auto') {
    await waitFor(async () => (await harness.has('#full-auto-title')) ? true : null, 5_000, 'full access confirmation')
    await harness.evaluate('document.querySelector(".danger-action")?.click()')
  }
  await waitFor(async () => await harness.evaluate<boolean>(`document.querySelector('[data-testid="composer-permission-mode"]')?.value === ${JSON.stringify(mode)}`) ? true : null, 5_000, `permission mode ${mode}`)
}

async function stopActiveTask(harness: DesktopCdpHarness, sessionId: string): Promise<void> {
  await harness.evaluate('document.querySelector("[data-testid=\\"composer-stop\\"]")?.click()')
  try {
    await waitFor(async () => await harness.evaluate<boolean>(`(() => {
      const state = document.querySelector('[data-testid="session-${sessionId}"] .session-state')?.className ?? '';
      const terminal = /state-(failed|cancelled|timed_out|succeeded|queued)/.test(state);
      const stop = document.querySelector('[data-testid="composer-stop"]');
      return terminal && stop == null;
    })()`) ? true : null, 15_000, 'GUI stop before next prompt')
  } catch {
    // Cleanup still records pending RPCs. Do not hide a stuck Stop by waiting forever.
  }
}

async function submitPrompt(
  harness: DesktopCdpHarness,
  prompt: string,
  sessionId: string,
  timeoutMs: number,
  screenshotsDir: string,
  approvals: string[]
): Promise<{ finalCount: number; beforeFinalCount: number; visibleFeedbackMs: number; sentAt: number }> {
  const stopAndDrain = async (): Promise<void> => {
    await stopActiveTask(harness, sessionId)
    try {
      await waitFor(async () => await harness.evaluate<boolean>(`(() => {
        const pending = document.querySelector('[data-testid="diagnostics-pending-rpc"]')?.textContent ?? '';
        return !/pending[^0-9]*[1-9]/i.test(pending);
      })()`) ? true : null, 10_000, 'GUI stop and RPC drain')
    } catch {
      // Cleanup still records pending RPCs and fails the run if the GUI stop
      // contract did not drain. Do not hide that defect by waiting forever.
    }
  }
  if (await harness.has('[data-testid="composer-stop"]')) {
    await stopAndDrain()
  }
  await waitFor(async () => await harness.evaluate<boolean>('!document.querySelector("[data-testid=\\"composer-input\\"]")?.disabled && !document.querySelector("[data-testid=\\"composer-stop\\"]")') ? true : null, 15_000, 'composer ready')
  const beforeFinalCount = await harness.evaluate<number>('document.querySelectorAll("[data-testid=\\"final-answer\\"]").length')
  const sentAt = Date.now()
  await harness.evaluate(`(() => {
    const watchdog = window.__rxyWatchdog || (window.__rxyWatchdog = { firstActivityAt: null, lastVisibleAt: Date.now(), inFlightTools: 0, pendingToolPrep: false, recoveryOpen: false });
    watchdog.firstActivityAt = null;
    watchdog.lastVisibleAt = Date.now();
    watchdog.inFlightTools = 0;
    watchdog.pendingToolPrep = false;
    watchdog.recoveryOpen = false;
  })()`)
  const beforeToolCount = await harness.evaluate<number>('document.querySelectorAll("[data-testid^=\\"timeline-tool-\\"]").length')
  await harness.typePrompt(prompt)
  await harness.pressKey('Enter')
  await waitFor(async () => {
    if (await harness.has('[data-testid="running-indicator"]')) return true
    const tools = await harness.evaluate<number>('document.querySelectorAll("[data-testid^=\\"timeline-tool-\\"]").length')
    return tools > beforeToolCount ? true : null
  }, 5_000, 'visible task feedback')
  const visibleFeedbackMs = Date.now() - sentAt
  let finalCount = await harness.evaluate<number>('document.querySelectorAll("[data-testid=\\"final-answer\\"]").length')
  const deadline = Date.now() + timeoutMs
  let approvalStateStartedAt: number | null = null
  let queuedStateStartedAt: number | null = null
  let failedStateStartedAt: number | null = null
  let sawActive = false
  while (Date.now() < deadline) {
    if (await harness.has('.approval-dialog .approve') || await harness.has('.approval-dialog .always-allow')) {
      const storm = approvalStormIssue(approvals.length + 1)
      if (storm !== null) {
        await stopAndDrain()
        throw new Error(storm)
      }
      const path = await harness.screenshot(join(screenshotsDir, `approval-${approvals.length + 1}.png`))
      const usedAlwaysAllow = await harness.evaluate<boolean>(`(() => {
        const always = document.querySelector('.approval-dialog .always-allow');
        if (always instanceof HTMLElement) { always.click(); return true; }
        document.querySelector('.approval-dialog .approve')?.click();
        return false;
      })()`)
      if (usedAlwaysAllow) {
        try {
          await waitFor(async () => (await harness.has('.approval-dialog .save-rule')) ? true : null, 5_000, 'always-allow scope form')
          await harness.evaluate(`(() => {
            const any = document.querySelector('.approval-dialog input[value="any"]');
            if (any instanceof HTMLInputElement) any.click();
            document.querySelector('.approval-dialog .save-rule')?.click();
          })()`)
        } catch (caught) {
          await stopAndDrain()
          throw new Error(`always-allow form did not complete: ${caught instanceof Error ? caught.message : String(caught)}`)
        }
      }
      approvals.push(`${usedAlwaysAllow ? 'always-allow workspace WRITE' : 'approved once'} via Desktop dialog; screenshot=${path}`)
      try {
        await waitFor(async () => (
          !(await harness.has('.approval-dialog .approve'))
          && !(await harness.has('.approval-dialog .save-rule'))
        ) ? true : null, 5_000, 'approval decision closes dialog')
      } catch (caught) {
        await stopAndDrain()
        throw new Error(`approval decision did not close the dialog: ${caught instanceof Error ? caught.message : String(caught)}`)
      }
    }
    finalCount = await harness.evaluate<number>('document.querySelectorAll("[data-testid=\\"final-answer\\"]").length')
    const state = await harness.evaluate<string | null>(`(() => {
      const node = document.querySelector('[data-testid="session-${sessionId}"] .session-state');
      const value = node?.className ?? '';
      return value.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/)?.[1] ?? null;
    })()`)
    if (state === 'queued' || state === 'running' || state === 'approval') {
      sawActive = true
    }
    if (sawActive && state !== null && !['queued', 'running', 'approval'].includes(state)) {
      // T04-1: APIConnectionError flipped the session to failed, then recovery
      // started a new run. Returning here cancelled that recovery and stub-repaired.
      // A leftover Failed from the previous prompt must not count as this prompt
      // finishing, and a stuck Stop button must not wait out the 45-minute timeout.
      const recovering = await harness.evaluate<boolean>('Boolean(window.__rxyWatchdog?.recoveryOpen)')
      if (state === 'failed' && (recovering || failedStateStartedAt === null || Date.now() - failedStateStartedAt < 15_000)) {
        failedStateStartedAt ??= Date.now()
      } else {
        return { finalCount, beforeFinalCount, visibleFeedbackMs, sentAt }
      }
    } else {
      failedStateStartedAt = null
    }
    if (state === 'approval') {
      approvalStateStartedAt ??= Date.now()
      if (Date.now() - approvalStateStartedAt > 15_000) {
        await stopAndDrain()
        throw new Error('approval state remained active without a visible decision dialog')
      }
    } else {
      approvalStateStartedAt = null
    }
    if (state === 'queued' || state === 'running') {
      const firstModelActivityAt = await harness.evaluate<number | null>('window.__rxyWatchdog?.firstActivityAt ?? null')
      if (state === 'queued') {
        queuedStateStartedAt ??= Date.now()
        // T06-1: after bash timeouts the session flickered to queued while the
        // model was still working. The 30s queued gate is only for a prompt
        // that never left the queue.
        if (firstModelActivityAt === null && Date.now() - queuedStateStartedAt > 30_000) {
          await stopAndDrain()
          throw new Error('task remained queued for more than 30s after submission')
        }
      } else {
        queuedStateStartedAt = null
      }
      if (state === 'running' && firstModelActivityAt === null && Date.now() - sentAt > 30_000) {
        await stopAndDrain()
        throw new Error(`first model activity exceeded 30s (${Date.now() - sentAt}ms); stopped through GUI`)
      }
      if (state === 'running' || firstModelActivityAt !== null) {
      const silentForMs = await harness.evaluate<number>(`(() => {
        const watchdog = window.__rxyWatchdog;
        if (watchdog != null && watchdog.recoveryOpen) return 0;
        const last = watchdog != null && typeof watchdog.lastVisibleAt === 'number' ? watchdog.lastVisibleAt : Date.now();
        const idle = Date.now() - last;
        if (watchdog != null && (Number(watchdog.inFlightTools) > 0 || watchdog.pendingToolPrep === true)) return idle > ${IN_FLIGHT_TOOL_STALL_MS} ? idle : 0;
        return idle;
      })()`)
      if (silentForMs > 30_000) {
        await stopAndDrain()
        throw new Error(`visible task event silent for ${silentForMs}ms; stopped through GUI`)
      }
      }
    }
    const wallIssue = taskWallClockIssue(Date.now() - sentAt)
    if (wallIssue !== null) {
      await stopAndDrain()
      throw new Error(wallIssue)
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500))
  }
  await stopAndDrain()
  throw new Error(`task timed out after ${timeoutMs}ms; stopped through GUI`)
}

async function startStaticServer(root: string): Promise<{ process: ChildProcess; port: number }> {
  const source = [
    "const http=require('node:http'),fs=require('node:fs'),path=require('node:path');",
    `const root=${JSON.stringify(root)};`,
    "const s=http.createServer((q,r)=>{",
    "const rel=decodeURIComponent(String((q.url||'/').split('?')[0])).replace(/^[\\\\/]+/,'')||'index.html';",
    "if(rel.split(/[\\\\/]/).includes('..')){r.statusCode=403;return r.end('forbidden')}",
    "const p=path.resolve(root,rel);",
    "const back=path.relative(path.resolve(root),p);",
    "if(back.startsWith('..')||back.split(/[\\\\/]/).includes('..')){r.statusCode=403;return r.end('forbidden')}",
    "const ext=path.extname(p);",
    "const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.csv':'text/csv; charset=utf-8','.md':'text/markdown; charset=utf-8'};",
    "if(types[ext]) r.setHeader('Content-Type', types[ext]);",
    "fs.createReadStream(p).on('error',()=>{r.statusCode=404;r.end('not found')}).pipe(r)",
    "});",
    "s.listen(0,'127.0.0.1',()=>console.log('PORT='+s.address().port));"
  ].join('')
  const child = spawn(process.execPath, ['-e', source], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  return await new Promise<{ process: ChildProcess; port: number }>((resolveServer, rejectServer) => {
    let buffer = ''
    const timer = setTimeout(() => {
      cleanup()
      rejectServer(new Error('generated web server did not announce a port within 10s'))
    }, 10_000)
    const onData = (chunk: Buffer | string): void => {
      buffer += chunk.toString()
      const match = buffer.match(/PORT=(\d+)/)
      if (match !== null) {
        cleanup()
        resolveServer({ process: child, port: Number(match[1]) })
      }
    }
    const onExit = (code: number | null): void => {
      cleanup()
      rejectServer(new Error(`generated web server exited before ready (code=${code ?? 'unknown'})`))
    }
    const cleanup = (): void => {
      clearTimeout(timer)
      child.stdout?.off('data', onData)
      child.off('exit', onExit)
    }
    child.stdout?.on('data', onData)
    child.once('exit', onExit)
  })
}

function stopProcess(child: ChildProcess): void {
  if (child.pid === undefined) return
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
  else child.kill('SIGTERM')
}

function chromeBinary(): string {
  const candidates = [
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    join(process.env['PROGRAMFILES(X86)'] ?? '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
  ].filter((value): value is string => typeof value === 'string' && value.length > 0)
  const found = candidates.find((path) => existsSync(path))
  if (found === undefined) throw new Error('Chrome/Edge missing for generated page interaction probe')
  return found
}

const gamePlayExpression = `(() => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const startSelector = '#btn-start, #startBtn, #start-btn, [data-action="start"], [data-action="newgame"], button.big, button.primary, .btn-primary, #screen-start button.btn:not(.alt)';
  const isShown = (node) => {
    if (!(node instanceof HTMLElement)) return false;
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 && box.width > 1 && box.height > 1;
  };
  const findStart = () => {
    const labeled = Array.from(document.querySelectorAll('button')).filter((button) => /开始|start|play|new\\s*game/i.test(button.textContent || '') && !/mute|help|pause|resume|restart|静音|帮助|暂停|继续|重新/.test(button.textContent || ''));
    const nodes = [...document.querySelectorAll(startSelector), ...labeled].filter((node) => node instanceof HTMLElement);
    return nodes.find((node) => isShown(node)) || nodes[0] || null;
  };
  const readScore = () => {
    const el = document.querySelector('#score, #scoreVal, #hud-score, #hud-coins, #stat-score, [data-testid="score"]');
    const n = Number(String((el && el.textContent) || '0').replace(/[^0-9.-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  };
  const overlayHidden = () => {
    const overlay = document.querySelector('#overlay-start, #screen-start, #screen-menu, #menu-screen, #overlay')
      || document.querySelector('#btn-start, [data-action="newgame"]')?.closest('.overlay, .screen');
    if (!(overlay instanceof HTMLElement)) return !isShown(findStart());
    if (overlay.classList.contains('hidden')) return true;
    const style = getComputedStyle(overlay);
    return style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0;
  };
  const readState = () => ({
    score: readScore(),
    state: ((document.querySelector('#stateLabel, #state') || {}).textContent || ''),
    title: document.title,
    overlayHidden: overlayHidden(),
    startVisible: isShown(findStart())
  });
  const press = (key) => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  };
  return (async () => {
    const start = findStart();
    if (start instanceof HTMLElement) {
      start.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      start.click();
      press('Enter');
    }
    let snapshot = readState();
    const canvas = document.querySelector('canvas');
    const canvasPainted = () => {
      if (!(canvas instanceof HTMLCanvasElement)) return false;
      try {
        const ctx = canvas.getContext('2d');
        if (!ctx) return false;
        const sample = ctx.getImageData(0, 0, Math.min(canvas.width, 48), Math.min(canvas.height, 48)).data;
        for (let i = 0; i < sample.length; i += 4) {
          if (sample[i] > 8 || sample[i + 1] > 8 || sample[i + 2] > 8) return true;
        }
      } catch {}
      return false;
    };
    for (let i = 0; i < 24 && snapshot.score <= 0 && !/running|playing|run|\\u8fd0\\u884c|\\u8fdb\\u884c|\\u6e38\\u73a9/i.test(snapshot.state) && (!snapshot.overlayHidden || snapshot.startVisible); i += 1) {
      if (start instanceof HTMLElement) start.click();
      press('ArrowUp'); press('ArrowRight');
      await sleep(250);
      snapshot = readState();
    }
    const started = snapshot.score > 0 || /running|playing|run|\\u8fd0\\u884c|\\u8fdb\\u884c|\\u6e38\\u73a9/i.test(snapshot.state);
    if (!started) return { ok: false, reason: start instanceof HTMLElement ? 'did not enter a running/playable state' : 'no start control', canvasPainted: canvasPainted(), ...snapshot };
    for (let i = 0; i < 40 && !/over|end|fail|\\u7ed3\\u675f|\\u5931\\u8d25/i.test(snapshot.state); i += 1) {
      press(' '); press('ArrowUp'); press('ArrowRight');
      await sleep(250);
      snapshot = readState();
    }
    const restart = document.querySelector('#restartBtn, #btn-restart');
    if (restart instanceof HTMLElement) restart.click(); else press('r');
    await sleep(400);
    return { ok: true, canvasPainted: canvasPainted(), ...snapshot, afterRestart: readState() };
  })();
})()`

const pagePlayExpression = `(() => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  return (async () => {
    const text = ((document.body && document.body.innerText) || '').trim();
    const button = document.querySelector('button, [type="button"], [type="submit"]');
    const samePage = document.querySelector('a[href^="#"]');
    const field = document.querySelector('select, input:not([type="hidden"]):not([type="file"])');
    const control = button || samePage || field;
    if (control instanceof HTMLElement) control.click();
    await sleep(300);
    const after = ((document.body && document.body.innerText) || '').trim();
    return {
      ok: after.length > 40 || text.length > 40,
      reason: (after.length > 40 || text.length > 40) ? undefined : 'page has no usable content',
      title: document.title,
      textLength: Math.max(text.length, after.length)
    };
  })();
})()`

const companyPagePlayExpression = `(() => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const countModules = (text) => {
    const hay = String(text || '');
    return [
      /用户管理|用户列表/i,
      /订单管理|订单列表/i,
      /内容管理|内容页面/i,
      /设置|settings/i,
      /分析|数据看板|统计|dashboard|analytics/i
    ].filter((pattern) => pattern.test(hay)).length;
  };
  const tryAdminFormLogin = async () => {
    const user = document.querySelector('#aUser, #login-username, #loginUsername, input[name="username"], input[type="text"]');
    const pass = document.querySelector('#aPass, #login-password, #loginPassword, input[name="password"], input[type="password"]');
    const form = document.querySelector('#authForm, #login-form, #loginForm, form');
    if (!(user instanceof HTMLInputElement) || !(pass instanceof HTMLInputElement)) return;
    user.value = user.defaultValue || 'admin';
    pass.value = pass.defaultValue || pass.getAttribute('value') || '123456';
    user.dispatchEvent(new Event('input', { bubbles: true }));
    pass.dispatchEvent(new Event('input', { bubbles: true }));
    if (form instanceof HTMLFormElement) {
      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn instanceof HTMLElement) submitBtn.click();
      else form.requestSubmit();
    } else {
      const submitBtn = document.querySelector('[type="submit"], #btn-login, button.login');
      if (submitBtn instanceof HTMLElement) submitBtn.click();
    }
    await sleep(800);
  };
  return (async () => {
    const text = ((document.body && document.body.innerText) || '').trim();
    if (text.length < 40) return { ok: false, reason: 'page has no usable content', textLength: text.length, demoClicked: false, adminModules: 0 };
    if (/admin\\.html/i.test(String(location.href || ''))) {
      let adminText = text;
      let adminModules = countModules(adminText);
      if (adminModules < 4) {
        await tryAdminFormLogin();
        adminText = ((document.body && document.body.innerText) || '').trim();
        adminModules = countModules(adminText);
      }
      return {
        ok: adminModules >= 4,
        reason: adminModules >= 4 ? undefined : 'demo login did not open an admin console',
        title: document.title,
        textLength: adminText.length,
        adminText: adminText.slice(0, 2000),
        demoClicked: true,
        navigated: true,
        adminModules
      };
    }
    const adminModulesNow = countModules(text);
    if (adminModulesNow >= 4) {
      return { ok: true, reason: undefined, title: document.title, textLength: text.length, adminText: text.slice(0, 2000), demoClicked: true, navigated: true, adminModules: adminModulesNow };
    }
    if (!document.querySelector('#btn-demo-login, [data-demo-login]')) {
      const loginLink = document.querySelector('a.btn-login, a[href*="login"], [data-open-login], #btn-login, button#btn-open-login:not([type="submit"])');
      if (loginLink instanceof HTMLElement) loginLink.click();
      await sleep(400);
    }
    const user = document.querySelector('#aUser, #login-username, #loginUsername, input[name="username"]');
    const pass = document.querySelector('#aPass, #login-password, #loginPassword, input[name="password"]');
    const form = document.querySelector('#authForm, #login-form, #loginForm');
    if (user instanceof HTMLInputElement && pass instanceof HTMLInputElement && form instanceof HTMLFormElement) {
      user.value = 'wrong';
      pass.value = 'wrong';
      user.dispatchEvent(new Event('input', { bubbles: true }));
      pass.dispatchEvent(new Event('input', { bubbles: true }));
      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn instanceof HTMLElement) submitBtn.click();
      else form.requestSubmit();
      await sleep(500);
    }
    const statusEl = document.querySelector('#login-status, #authError, #statusMsg, .form-status, .status-msg, [role="alert"]');
    const status = ((statusEl && statusEl.textContent) || '').trim();
    const demo = document.querySelector('#btn-demo-login, [data-demo-login]');
    if (demo instanceof HTMLElement) {
      demo.click();
      demo.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    }
    await sleep(1500);
    let after = ((document.body && document.body.innerText) || '').trim();
    let adminModules = countModules(after);
    if (adminModules < 4) {
      const demoUser = document.querySelector('#aUser, #login-username, #loginUsername');
      const demoPass = document.querySelector('#aPass, #login-password, #loginPassword');
      const demoForm = document.querySelector('#authForm, #login-form, #loginForm');
      if (demoUser instanceof HTMLInputElement && demoPass instanceof HTMLInputElement && demoForm instanceof HTMLFormElement) {
        demoUser.value = demoUser.defaultValue || 'admin';
        demoPass.value = demoPass.defaultValue || demoPass.getAttribute('value') || '';
        const demoSubmit = demoForm.querySelector('[type="submit"]');
        if (demoSubmit instanceof HTMLElement) demoSubmit.click();
        else demoForm.requestSubmit();
        await sleep(1200);
        after = ((document.body && document.body.innerText) || '').trim();
        adminModules = countModules(after);
      }
    }
    const demoClicked = demo instanceof HTMLElement;
    return {
      ok: demoClicked && adminModules >= 4,
      reason: demoClicked ? (adminModules >= 4 ? undefined : 'demo login did not open an admin console') : 'company page has no working demo login (#btn-demo-login)',
      title: document.title,
      textLength: after.length,
      adminText: after.slice(0, 2000),
      loginOpened: Boolean(document.querySelector('#login-modal:not([hidden]), #authModal:not([hidden]), #login-form, #loginForm, dialog[open]')),
      wrongLoginFeedback: status.length > 0,
      demoClicked,
      adminModules
    };
  })();
})()`

async function evaluateInChrome(
  url: string,
  expression: string,
  screenshotFile: string,
  afterNavigationExpression?: string
): Promise<Record<string, any>> {
  const profileDir = mkdtempSync(join(tmpdir(), 'rxy-chrome-play-'))
  const child = spawn(chromeBinary(), [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-background-networking',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
    `--user-data-dir=${profileDir}`,
    '--remote-debugging-port=0',
    url
  ], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let socket: WebSocket | null = null
  try {
    const activePortFile = join(profileDir, 'DevToolsActivePort')
    const debugPort = await waitFor(async () => {
      if (!existsSync(activePortFile)) return null
      const value = Number(readFileSync(activePortFile, 'utf8').split(/\r?\n/)[0])
      return Number.isInteger(value) && value > 0 ? value : null
    }, 20_000, 'Chrome DevToolsActivePort')
    const target = await waitFor(async () => {
      try {
        const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json() as Array<{ type: string; url?: string; webSocketDebuggerUrl?: string }>
        return selectRendererTarget(pages)
      } catch {
        return null
      }
    }, 15_000, 'Chrome page target')
    socket = new WebSocket(target)
    await new Promise<void>((resolveOpen, rejectOpen) => {
      socket!.onopen = () => resolveOpen()
      socket!.onerror = () => rejectOpen(new Error('Chrome CDP websocket failed'))
    })
    let sequence = 0
    const pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>()
    let pageReady = false
    let pageReadyResolve: (() => void) | undefined
    const pageExceptions: string[] = []
    const attachSocket = (next: WebSocket): void => {
      next.onmessage = (event) => {
        const message = JSON.parse(String(event.data)) as {
          id?: number
          method?: string
          params?: { name?: string; exceptionDetails?: { text?: string; exception?: { description?: string } } }
          error?: unknown
          result?: unknown
        }
        if (message.method === 'Runtime.exceptionThrown') {
          const details = message.params?.exceptionDetails
          const text = String(details?.exception?.description ?? details?.text ?? '').trim()
          if (text.length > 0) pageExceptions.push(text.slice(0, 800))
        }
        if (message.method === 'Page.loadEventFired' || (message.method === 'Page.lifecycleEvent' && (message.params?.name === 'DOMContentLoaded' || message.params?.name === 'load'))) {
          pageReady = true
          pageReadyResolve?.()
          return
        }
        if (message.id === undefined) return
        const entry = pending.get(message.id)
        if (entry === undefined) return
        pending.delete(message.id)
        if (message.error !== undefined) entry.reject(new Error(JSON.stringify(message.error)))
        else entry.resolve(message.result)
      }
    }
    attachSocket(socket)
    const send = (method: string, params: unknown = {}, timeoutMs = 30_000): Promise<any> => new Promise((resolveSend, rejectSend) => {
      const id = ++sequence
      const timer = setTimeout(() => {
        pending.delete(id)
        rejectSend(new Error(`Chrome CDP timed out: ${method}`))
      }, timeoutMs)
      pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolveSend(value) },
        reject: (error) => { clearTimeout(timer); rejectSend(error) }
      })
      socket!.send(JSON.stringify({ id, method, params }))
    })
    const waitForPageReady = async (): Promise<void> => {
      if (pageReady) return
      await Promise.race([
        new Promise<void>((resolveWait) => { pageReadyResolve = resolveWait }),
        new Promise<void>((resolveWait) => setTimeout(resolveWait, 2500))
      ])
    }
    await send('Runtime.enable')
    await send('Page.enable')
    await send('Page.setLifecycleEventsEnabled', { enabled: true })
    pageReady = false
    await send('Page.navigate', { url })
    await waitForPageReady()
    const evaluatePage = async (expr: string): Promise<any> => {
      const evaluated = await send('Runtime.evaluate', {
        expression: expr,
        awaitPromise: true,
        returnByValue: true,
        userGesture: true
      }, 35_000)
      if (evaluated.exceptionDetails !== undefined) {
        throw new Error(evaluated.exceptionDetails.text ?? 'page expression threw')
      }
      return evaluated.result?.value ?? {}
    }
    let value: Record<string, any> = {}
    const reconnectAfterNavigation = async (): Promise<void> => {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 700))
      try { socket?.close() } catch {}
      const nextTarget = await waitFor(async () => {
        try {
          const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json() as Array<{ type: string; url?: string; webSocketDebuggerUrl?: string }>
          return selectRendererTarget(pages)
        } catch {
          return null
        }
      }, 15_000, 'Chrome page target after navigation')
      socket = new WebSocket(nextTarget)
      await new Promise<void>((resolveOpen, rejectOpen) => {
        socket!.onopen = () => resolveOpen()
        socket!.onerror = () => rejectOpen(new Error('Chrome CDP websocket failed after navigation'))
      })
      sequence = 0
      pending.clear()
      pageReady = false
      attachSocket(socket)
      await send('Runtime.enable')
      await send('Page.enable')
      await send('Page.setLifecycleEventsEnabled', { enabled: true })
      await waitForPageReady()
    }
    for (let hop = 0; hop < 5; hop += 1) {
      const expr = hop === 0
        ? expression
        : (afterNavigationExpression ?? expression)
      try {
        value = await evaluatePage(expr)
        break
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught)
        if (!/navigated or closed/i.test(message)) throw caught
        if (hop === 4) throw caught
        await reconnectAfterNavigation()
      }
    }
    try {
      const image = await send('Page.captureScreenshot', { format: 'png' }, 10_000)
      if (typeof image.data === 'string') writeFileSync(screenshotFile, Buffer.from(image.data, 'base64'))
    } catch {}
    if (pageExceptions.length > 0) {
      return { ...value, pageExceptions: [...new Set(pageExceptions)].slice(0, 8) }
    }
    return value
  } finally {
    try { socket?.close() } catch {}
    stopProcess(child)
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 400))
    try {
      rmSync(profileDir, { recursive: true, force: true })
    } catch {
      // Chrome may keep the profile directory locked on Windows. Probe
      // success must not depend on deleting that scratch directory.
    }
  }
}

async function playGeneratedWebPage(source: string, port: number, mode: 'game' | 'page' | 'company' = 'game'): Promise<string | null> {
  const screenshotFile = join(source, '.rxy-play-probe.png')
  try {
    const parsed = await evaluateInChrome(
      `http://127.0.0.1:${port}/`,
      mode === 'company' ? companyPagePlayExpression : mode === 'page' ? pagePlayExpression : gamePlayExpression,
      screenshotFile,
      mode === 'company' ? companyPagePlayExpression : undefined
    ) as { ok?: boolean; score?: number; state?: string; reason?: string; overlayHidden?: boolean; startVisible?: boolean; demoClicked?: boolean; navigated?: boolean; adminModules?: number; adminText?: string; pageExceptions?: string[] }
    writeFileSync(join(source, '.rxy-play-probe.json'), JSON.stringify(parsed, null, 2))
    if (mode === 'company') {
      const probeIssue = companyLoginProbeIssue(parsed)
      if (probeIssue !== null) return probeIssue
    } else if (parsed.ok !== true) {
      const exceptions = Array.isArray(parsed.pageExceptions) ? parsed.pageExceptions.join('; ') : ''
      return `generated page is not playable: ${parsed.reason ?? 'unknown'} (state=${String(parsed.state ?? '')}, score=${String(parsed.score ?? 0)})${exceptions ? `; page JS exception: ${exceptions}` : ''}`
    }
    if (mode === 'game' && Array.isArray(parsed.pageExceptions) && parsed.pageExceptions.length > 0) {
      return `generated page threw JS exceptions: ${parsed.pageExceptions.join('; ')}`
    }
    if (mode === 'game' && gameMenuStillBlockingPlay({
      overlayHidden: parsed.overlayHidden === true,
      startVisible: parsed.startVisible === true,
      state: String(parsed.state ?? ''),
      score: Number(parsed.score ?? 0)
    })) {
      const exceptions = Array.isArray(parsed.pageExceptions) ? parsed.pageExceptions.join('; ') : ''
      return `generated page did not enter a running/playable state (state=${String(parsed.state ?? '')}, score=${String(parsed.score ?? 0)})${exceptions ? `; page JS exception: ${exceptions}` : ''}`
    }
    return null
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : String(caught)
    writeFileSync(join(source, '.rxy-play-probe.json'), JSON.stringify({ error: message }, null, 2))
    return `generated page interaction probe failed: ${message}`
  }
}

function redactSecrets(text: string): string {
  return text.replace(/(password|pwd|passwd)\s*[:=]\s*\S+/gi, '$1=***')
}

function summarizeMvnOutput(out: string): string {
  const errors = [...out.matchAll(/^\[ERROR\].+$/gm)].map((match) => match[0])
  const causes = [...out.matchAll(/^Caused by: .+$/gm)].map((match) => match[0])
  const beans = [...out.matchAll(/Error creating bean with name '[^']+'/g)].map((match) => match[0])
  const tables = [...out.matchAll(/Table '[^']+' does(?:n't| not) exist/g)].map((match) => match[0])
  const asserts = [...out.matchAll(/Status expected:<[^>]+> but was:<[^>]+>/g)].map((match) => match[0])
  const csrf403 = [...out.matchAll(/Status expected:<20[01]> but was:<403>/g)].map((match) => match[0])
  const rolePrefix = [...out.matchAll(/ROLE_[A-Z]+ cannot start with ROLE_/g)].map((match) => match[0])
  const symbols = [...out.matchAll(/^\[ERROR\].*(?:找不到符号|cannot find symbol|PluginContainerException|flyway-maven-plugin).*$/gm)].map((match) => match[0])
  const missingTypes = [...out.matchAll(/^\[ERROR\]\s+(?:符号|symbol)\s*:\s*(?:类|class)\s+\S+.*$/gm)].map((match) => match[0])
  const flywayVal = [...out.matchAll(/FlywayValidateException: .+$/gm)].map((match) => match[0])
  const checksum = [...out.matchAll(/Migration checksum mismatch[^\n]*/g)].map((match) => match[0])
  const flywayEmpty = [...out.matchAll(/Found non-empty schema[^\n]*/g)].map((match) => match[0])
  const jdbcQuery = [...out.matchAll(/executeQuery\(\) cannot issue statements[^\n]*/g)].map((match) => match[0])
  const bootCfg = [...out.matchAll(/Unable to find a @SpringBootConfiguration[^\n]*/g)].map((match) => match[0])
  const notNull = [...out.matchAll(/Column '[^']+' cannot be null[^\n]*/g)].map((match) => match[0])
  const lazy = [...out.matchAll(/LazyInitializationException[^\n]*/g)].map((match) => match[0])
  const jacksonEnum = [...out.matchAll(/No enum constant tools\.jackson[^\n]*/g)].map((match) => match[0])
  const extra = [...new Set([...causes.slice(-8), ...beans.slice(-4), ...tables.slice(-4), ...asserts.slice(-4), ...csrf403.slice(-4), ...rolePrefix.slice(-4), ...symbols.slice(-8), ...missingTypes.slice(-12), ...flywayVal.slice(-4), ...checksum.slice(-4), ...flywayEmpty.slice(-4), ...jdbcQuery.slice(-4), ...bootCfg.slice(-4), ...notNull.slice(-4), ...lazy.slice(-4), ...jacksonEnum.slice(-4)])]
  const parts = [...errors.slice(-12), ...extra]
  if (parts.length > 0) return parts.join('\n').slice(0, 4000)
  return out.slice(-1200)
}

function mysqlClientBin(): string | null {
  const which = process.platform === 'win32' ? 'where.exe' : 'which'
  const located = spawnSync(which, ['mysql'], { encoding: 'utf8', windowsHide: true, timeout: 10_000 })
  const found = String(located.stdout ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.length > 0 && existsSync(line))
  if (found !== undefined) return found
  const fallbacks = [
    'C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysql.exe',
    'C:\\Program Files\\MySQL\\MySQL Server 8.4\\bin\\mysql.exe'
  ]
  return fallbacks.find((file) => existsSync(file)) ?? null
}

function resetMysqlTestSchema(): string | null {
  const env = mysqlTestEnv()
  const db = env.MYSQL_DATABASE ?? ''
  const user = env.MYSQL_USER ?? ''
  const userPassword = env.MYSQL_PASSWORD ?? ''
  if (!/^rxycode_t0\d+$/i.test(db) || !/^[A-Za-z0-9_]+$/.test(user) || userPassword.length === 0) {
    return 'mysql schema reset skipped: MYSQL_DATABASE/MYSQL_USER/MYSQL_PASSWORD are missing or unsafe'
  }
  const bin = mysqlClientBin()
  if (bin === null) return 'mysql schema reset failed: mysql client was not found'
  const host = env.MYSQL_HOST ?? '127.0.0.1'
  const port = env.MYSQL_PORT ?? '3306'
  const runSql = (account: string, password: string, args: string[], sql: string) => spawnSync(
    bin,
    ['--protocol=TCP', '-h', host, '-P', port, '-u', account, ...args, '-N', '-e', sql],
    { env: { ...process.env, MYSQL_PWD: password }, encoding: 'utf8', windowsHide: true, timeout: 30_000 }
  )
  const adminPassword = env.MYSQL_ADMIN_PASSWORD ?? ''
  if (adminPassword.length > 0) {
    const listed = runSql('root', adminPassword, [], `SELECT id FROM information_schema.processlist WHERE db='${db}' AND id <> CONNECTION_ID()`)
    for (const id of String(listed.stdout ?? '').split(/\s+/)) {
      if (!/^\d+$/.test(id)) continue
      runSql('root', adminPassword, [], `KILL ${id}`)
    }
    const drop = runSql('root', adminPassword, [], [
      `DROP DATABASE IF EXISTS \`${db}\``,
      `CREATE DATABASE \`${db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`,
      `GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'localhost'`,
      `GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${user}'@'%'`,
      'FLUSH PRIVILEGES'
    ].join('; '))
    if (drop.status === 0) return null
  }
  const wipe = runSql(user, userPassword, ['-D', db], [
    'SET FOREIGN_KEY_CHECKS=0',
    'SET GROUP_CONCAT_MAX_LEN=1000000',
    `SET @tables = (SELECT GROUP_CONCAT(CONCAT('\`', table_name, '\`')) FROM information_schema.tables WHERE table_schema='${db}' AND table_type='BASE TABLE')`,
    "SET @sql = IF(@tables IS NULL OR @tables = '', 'DO 0', CONCAT('DROP TABLE IF EXISTS ', @tables))",
    'PREPARE stmt FROM @sql',
    'EXECUTE stmt',
    'DEALLOCATE PREPARE stmt',
    `SET @views = (SELECT GROUP_CONCAT(CONCAT('\`', table_name, '\`')) FROM information_schema.tables WHERE table_schema='${db}' AND table_type='VIEW')`,
    "SET @vsql = IF(@views IS NULL OR @views = '', 'DO 0', CONCAT('DROP VIEW IF EXISTS ', @views))",
    'PREPARE vstmt FROM @vsql',
    'EXECUTE vstmt',
    'DEALLOCATE PREPARE vstmt',
    'DROP TABLE IF EXISTS `flyway_schema_history`, `users`, `products`, `inventory`, `orders`, `order_items`',
    'SET FOREIGN_KEY_CHECKS=1'
  ].join('; '))
  if (wipe.status !== 0) {
    return `mysql schema reset failed: ${redactSecrets(String(wipe.stderr || wipe.stdout || 'could not drop tables')).slice(0, 500)}`
  }
  const remain = runSql(user, userPassword, ['-D', db], `SELECT table_name FROM information_schema.tables WHERE table_schema='${db}'`)
  const leftover = String(remain.stdout ?? '').replace(/\0/g, '').split(/\s+/).filter((name) => /^[A-Za-z0-9_]+$/.test(name))
  if (remain.status !== 0 || leftover.length > 0) {
    return `mysql schema reset failed: leftover tables ${leftover.join(',') || redactSecrets(String(remain.stderr || 'unknown')).slice(0, 200)}`
  }
  return null
}

function decodeXmlEntities(text: string): string {
  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
}

function surefireText(source: string): string {
  const dir = join(source, 'target', 'surefire-reports')
  if (!existsSync(dir)) return ''
  const chunks: string[] = []
  for (const name of readdirSync(dir)) {
    let body = ''
    try { body = readFileSync(join(dir, name), 'utf8') } catch { continue }
    if (/\.txt$/i.test(name)) {
      chunks.push(body)
      continue
    }
    if (!/\.xml$/i.test(name)) continue
    const decoded = decodeXmlEntities(body)
    const messages = [...decoded.matchAll(/<(?:failure|error)\b[^>]*message="([^"]*)"/g)].map((match) => match[1])
    const types = [...decoded.matchAll(/<(?:failure|error)\b[^>]*type="([^"]*)"/g)].map((match) => match[1])
    const boot = [...decoded.matchAll(/Unable to find a @SpringBootConfiguration[^\n<]*/g)].map((match) => match[0])
    chunks.push([...messages, ...types, ...boot].join('\n'))
  }
  return chunks.join('\n').slice(0, 6000)
}

function runProjectLocalMvnTest(source: string, files: string[]): { summary: string | null; error: string | null } {
  const relativeMaven = findProjectLocalMaven(files)
  if (relativeMaven === null) return { summary: null, error: null }
  const mvn = join(source, relativeMaven)
  const pom = join(source, 'pom.xml')
  if (!existsSync(mvn) || !existsSync(pom)) return { summary: null, error: null }
  const resetError = resetMysqlTestSchema()
  if (resetError !== null) return { summary: null, error: resetError }
  const env = {
    ...process.env,
    ...mysqlTestEnv(),
    JAVA_TOOL_OPTIONS: '-Dfile.encoding=UTF-8',
    MAVEN_OPTS: '-Dfile.encoding=UTF-8'
  }
  const args = ['-f', pom, 'test', '-Dfile.encoding=UTF-8']
  const result = process.platform === 'win32'
    ? spawnSync(
      process.env.ComSpec || 'cmd.exe',
      ['/d', '/s', '/c', [mvn, ...args].map((part) => (/\s/.test(part) ? `"${part}"` : part)).join(' ')],
      { cwd: source, env, encoding: 'utf8', timeout: 480_000, windowsHide: true, shell: false }
    )
    : spawnSync(mvn, args, { cwd: source, env, encoding: 'utf8', timeout: 480_000, windowsHide: true, shell: false })
  const out = redactSecrets(`${result.stdout ?? ''}\n${result.stderr ?? ''}\n${surefireText(source)}`)
  if (/Downloading Maven|找不到指定的路径|The system cannot find the path specified/i.test(out)) {
    return { summary: null, error: 'spring-mysql artifact has no project-local Maven (mvnw or .tools/apache-maven)' }
  }
  const countIssue = mavenTestCountsIssue(out)
  const summary = [...out.matchAll(/Tests run:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+/g)].at(-1)?.[0]
    ?? out.match(/Tests run:\s*[1-9][^\n]*/)?.[0]
    ?? null
  if (result.status !== 0 || /BUILD FAILURE/i.test(out) || countIssue !== null) {
    const compileFailed = /BUILD FAILURE|COMPILATION ERROR|找不到符号/i.test(out)
    return {
      summary,
      error: `mvn test failed:\n${compileFailed ? '' : (countIssue ?? '')}\n${summarizeMvnOutput(out)}`.trim()
    }
  }
  if (summary === null) {
    return { summary: null, error: `mvn test produced no Tests run: N line:\n${summarizeMvnOutput(out)}` }
  }
  return { summary, error: null }
}

async function smokeArtifact(scenario: RealBusinessScenario, source: string): Promise<string | null> {
  if (scenario.id === 'T09' || scenario.artifactKind === 'spring-mysql') {
    const underscored = join(dirname(source), scenario.outputDir.replaceAll('-', '_'))
    const dirIssue = missingOutputDirIssue(
      scenario.outputDir,
      existsSync(source),
      underscored !== source && existsSync(underscored)
    )
    if (dirIssue !== null) return dirIssue
  } else if (!existsSync(source)) {
    return 'output directory was not created'
  }
  if (scenario.artifactKind === 'web') {
    const files = listFiles(source)
    const missing = missingWebDeliverables(files)
    if (missing.length > 0) return `web artifact is incomplete; missing ${missing.join(', ')}`
    if (scenario.id === 'T03') {
      const companyIssue = companyWebsiteArtifactIssue(files, (rel) => {
        const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
        return readFileSync(join(source, disk), 'utf8')
      })
      if (companyIssue !== null) return companyIssue
    }
    if (scenario.id === 'T04') {
      const travelIssue = travelWebsiteArtifactIssue(files, (rel) => {
        const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
        return readFileSync(join(source, disk), 'utf8')
      })
      if (travelIssue !== null) return travelIssue
    }
    if (scenario.id === 'T06') {
      const biIssue = marketBiArtifactIssue(files, (rel) => {
        const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
        return readFileSync(join(source, disk), 'utf8')
      })
      if (biIssue !== null) return biIssue
    }
    if (scenario.id === 'T07') {
      const evIssue = evTcoArtifactIssue(files, (rel) => {
        const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
        return readFileSync(join(source, disk), 'utf8')
      })
      if (evIssue !== null) return evIssue
    }
    if (scenario.id === 'T08') {
      const rentalIssue = rentalDecisionArtifactIssue(files, (rel) => {
        const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
        return readFileSync(join(source, disk), 'utf8')
      })
      if (rentalIssue !== null) return rentalIssue
    }
    const serveRoot = webServeRoot(source, files)
    let server: { process: ChildProcess; port: number } | null = null
    try {
      server = await startStaticServer(serveRoot)
      const response = await fetch(`http://127.0.0.1:${server.port}/`)
      if (!response.ok) return `generated web server returned ${response.status}`
      if (scenario.id === 'T03') {
        const playError = await playGeneratedWebPage(source, server.port, 'company')
        if (playError !== null) return playError
      } else if (scenario.id === 'T01' || scenario.id === 'T02') {
        const playError = await playGeneratedWebPage(source, server.port, 'game')
        if (playError !== null) return playError
      } else {
        const playError = await playGeneratedWebPage(source, server.port, 'page')
        if (playError !== null) return playError
      }
    } finally {
      if (server !== null) stopProcess(server.process)
    }
  }
  if (scenario.artifactKind === 'spring-mysql' || scenario.id === 'T09') {
    const files = listFiles(source)
    const issue = springMysqlArtifactIssue(files, (rel) => {
      const disk = files.find((file) => file.replace(/\\/g, '/') === rel) ?? rel
      return readFileSync(join(source, disk), 'utf8')
    })
    if (issue !== null && /starter-flyway/i.test(issue)) return issue
    if (issue !== null && /H2\/SQLite|jdbc:h2/i.test(issue)) return issue
    if (issue !== null && /class-load|MockMvc/i.test(issue)) return issue
    if (issue !== null && /SpringBootConfiguration/i.test(issue)) return issue
    if (issue !== null && /write-dates-as-timestamps|Jackson 3/i.test(issue)) return issue
    if (issue !== null && /fasterxml\.jackson\.databind|autoconfigure\.webmvc/i.test(issue)) return issue
    if (issue !== null && /Flyway SQL|ddl-auto=validate|created menus/i.test(issue)) return issue
    const hasJava = files.some((file) => file.endsWith('.java'))
    const mvn = hasJava ? runProjectLocalMvnTest(source, files) : { summary: null, error: null }
    if (mvn.error !== null) return mvn.error
    const reportOnly = issue !== null && /TEST-REPORT|placeholders|Maven test counts/i.test(issue)
    if (issue !== null && !reportOnly) return issue
    if (issue !== null && mvn.summary !== null) {
      return `${issue}; harness mvn test observed: ${mvn.summary}`
    }
    return issue
  }
  if (scenario.id === 'T05') {
    const javaFiles = listFiles(source).filter((file) => file.endsWith('.java'))
    if (javaFiles.length === 0) return 'Java artifact has no .java source'
    const required = ['README.md', 'DEVELOPMENT.md', 'TEST-REPORT.md']
    const missing = required.filter((file) => !hasScenarioDoc(source, file))
    if (missing.length > 0) return `Java artifact is incomplete; missing ${missing.join(', ')}`
    const classOut = join(source, '.rxy-javac-out')
    mkdirSync(classOut, { recursive: true })
    const compile = spawnSync('javac', ['-encoding', 'UTF-8', '-d', classOut, ...javaFiles], { cwd: source, windowsHide: true, encoding: 'utf8', timeout: 120_000 })
    if (compile.status !== 0) return `javac failed: ${String(compile.stderr).slice(0, 1000)}`
    const mains = javaFiles.map((file) => ({ path: file, source: readFileSync(join(source, file), 'utf8') }))
    const mainClass = selectJavaSwingMain(mains)
    if (mainClass === null) return 'Java artifact has no Swing JFrame main(String[]) entry point'
    const launched = spawn('java', ['-cp', classOut, mainClass], { cwd: source, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    let stderr = ''
    launched.stderr?.on('data', (chunk) => { stderr += String(chunk) })
    try {
      await new Promise((resolve) => setTimeout(resolve, 2500))
      if (launched.exitCode !== null) {
        return `Swing process exited immediately with ${launched.exitCode}: ${stderr}`.slice(0, 500)
      }
    } finally {
      stopProcess(launched)
    }
  }
  return null
}

function buildArtifactRepairPrompt(scenario: RealBusinessScenario, validationError: string): string {
  return [
    `Artifact repair pass for ${scenario.id}. The previous turn was incomplete and failed validation. Work on the existing ${scenario.outputDir} only.`,
    `Validation failure: ${validationError}`,
    'Inspect the existing Txx files with ls or glob, then implement the missing work now. Do not probe python, node, pip, pandas, or the network with bash. Do not write _probe.py. Do not only explain or return a code snippet. Do not claim success without executing the real validation command.',
    `If the validation failure names missing files, call the write tool now with filePath inside ${scenario.outputDir} for each missing file. A table or Final Answer that lists the filename is not sufficient.`,
    scenario.artifactKind === 'web'
      ? (
        scenario.id === 'T01' || scenario.id === 'T02'
          ? 'For this game artifact, create a complete index.html entry point plus README.md and TEST-REPORT.md, start a local static server, and actually play the page. Fix JavaScript syntax/runtime errors so Start hides the menu overlay, #btn-start is no longer visible, a DOM #score/#stateLabel updates, score can increase, collision or game-over can occur, and restart works. A painted canvas behind a still-visible Start button is not playing. Do not claim success if the page stays on a menu or throws Uncaught SyntaxError. If the probe reports Identifier has already been declared (for example TILE in two classic scripts), rename or share one global and keep Start working.'
          : scenario.id === 'T03'
            ? 'For T03, call the write tool or edit. The no-websearch rule does not forbid write, ls, or edit. Put a real button with id="btn-demo-login" in index.html; clicking it must set location.href to admin.html (not only open a modal) so the harness reaches the admin console within one second. If README.md or TEST-REPORT.md are missing, write those two files immediately and do not only re-read admin.js. If login redirects to admin.html, that file must exist with visible 用户管理, 订单管理, 内容管理, 设置, and 分析 navigation. Required: PLAN.md, public home/products/team/cases/contact, #btn-open-login, failed-login status, #btn-demo-login, localStorage admin CRUD, README.md, and TEST-REPORT.md. Java, Spring, Maven, pom.xml, or a /api backend is a hard failure. A three-file stub without a real company site is a hard failure; README.md and TEST-REPORT.md are still required once the site exists. A department/employee CRUD page is not the product.'
            : scenario.id === 'T04'
              ? 'For T04, call the write tool. Do not emit a three-file index.html/README.md/TEST-REPORT.md stub. Required: PLAN.md, sources.md, a budget CSV, an interactive index.html with daily timetable, city switch, cost categories, total-budget validation (hard cap CNY 3000), rain plan, alternatives, price-change warnings, and one makeup/styling session, plus README.md and TEST-REPORT.md. Record source URLs and uncertainty; do not invent live inventory. A static table without select/input/button controls is a hard failure.'
              : scenario.id === 'T06'
                ? 'For T06, call the write tool immediately. Do not call bash, python, node, or download_file, and do not write _probe.py. Do not emit a three-file stub or a static table-only snapshot. index.html must contain literal <select> or <input> and <button> tags for date range, asset, and metric. Required: sources.md, raw and cleaned CSVs, that interactive BI index.html, plus README.md and TEST-REPORT.md. Mark inaccessible data unavailable; do not fabricate prices.'
                : scenario.id === 'T07'
                  ? 'For T07, call the write tool immediately. Do not call bash, python, or node, and do not write _probe.py. Do not emit a three-file stub. Do not load Chart.js or any CDN. Close every HTML tag. Draw charts with native canvas. Required: sources.md, data CSV, an interactive EV TCO index.html with Guangzhou family coverage, CNY 150k-250k budget, five-year TCO, mileage and weight controls, recommendation, and risk disclosure, plus README.md and TEST-REPORT.md. Mark inaccessible prices unavailable; do not fabricate live promotions.'
                  : scenario.id === 'T08'
                    ? 'For T08, call the write tool immediately. Do not call bash, python, node, Java, Spring, or Maven, and do not write _probe.py or pom.xml. Do not emit a three-file stub. Do not load Chart.js or any CDN. Close every HTML tag. Put a visible 合同与风险 section in index.html covering 合同条款, 解约/退租, 噪音, and 维修. Required: sources.md, data CSV, an interactive rental index.html with Zhujiang New Town commute coverage, CNY 3500 rent cap, 60-minute commute cap, filters, ranking, schematic map, moving calendar, contract/risk checklist, and weights, plus README.md and TEST-REPORT.md. Do not fabricate exact listings.'
                    : `For this web artifact, call the write tool now for ${scenario.outputDir}/index.html, ${scenario.outputDir}/README.md, and ${scenario.outputDir}/TEST-REPORT.md. Build the requested site (not a parkour/platformer game): public pages, demo login, and the admin/console interactions named in the checkpoints. Start a local static server and actually click through login, persistence, and logout. Do not substitute a game Start overlay for the required product.`
      )
      : scenario.artifactKind === 'java-swing'
        ? 'For the Java artifact, compile with javac -encoding UTF-8 -d a classes directory that preserves packages, then launch the Swing JFrame main (not *Test or *Driver). java -cp <project-root> com.example.Main cannot see classes under src/main/java. HTML or a screenshot is not an acceptable substitute.'
        : scenario.artifactKind === 'spring-mysql'
          ? `For this Spring/MySQL artifact, ${buildSpringMysqlRepairInstructions(validationError)} A markdown fence or Final Answer is not a write. Do not probe mysql/env again.`
          : 'For this application artifact, run the smallest real build and smoke test available; do not substitute a description for execution.',
    `The required visible checkpoints are: ${scenario.visualCheckpoints.join(', ')}. Verify them if the environment supports them and record unavailable capabilities honestly.`,
    scenario.artifactKind === 'spring-mysql'
      ? 'This is a local artifact repair pass. Do not call websearch or webfetch. You must call bash to run project-local mvn test or API smoke with MYSQL_* from the environment, then write TEST-REPORT.md. Do not skip tests. Do not probe python or rewrite the schema host.'
      : 'This is a local artifact repair pass. Do not call or use websearch, webfetch, browsing, internet, bash environment probes, or external research. Use only write, ls, glob, and edit; this prohibition is intentional even if the validation text contains words such as current, status, or source.',
    'Keep all files inside the requested Txx directory. End with a non-empty Final Answer listing the files changed, commands actually executed, results, and remaining risks.'
  ].join('\n\n')
}

function buildArtifactRepairPromptLegacy(scenario: RealBusinessScenario, validationError: string): string {
  return [
    `Artifact repair pass for ${scenario.id}. Inspect the existing ${scenario.outputDir}, fix the root cause now, and run the real validation command. Do not only explain, do not claim success without executing, and do not write outside this Txx directory. End with a non-empty Final Answer listing files, commands, actual results, and remaining risks.`,
    `这是对 ${scenario.id} 的真实验收修复轮，不是让你解释问题。你刚才生成的 ${scenario.outputDir} 未通过验收：`,
    validationError,
    '请立即检查当前工作区中已经生成的全部文件，定位根因并直接修复。不要只返回代码片段，不要声称“应该可以”。必须实际执行与产物类型对应的验证命令，直到验证命令成功：Java 必须对所有源码使用 javac -encoding UTF-8 编译；网页必须启动并检查入口；其他项目必须运行最小构建/测试。修复后重新检查文件清单、README 和 TEST-REPORT，并在 Final Answer 中明确列出实际修复、实际命令、实际结果和仍未完成的风险。不要写入任何其他 Txx 目录或用户目录。'
  ].join('\n\n')
}

async function runScenario(
  harness: DesktopCdpHarness,
  scenario: RealBusinessScenario,
  batch: Batch,
  prompt: string,
  sessionId: string,
  model: string,
  gateway: string,
  batchDir: string
): Promise<RealBusinessResult> {
  const startedAt = Date.now()
  const approvals: string[] = []
  const screenshots: string[] = []
  const outputSource = join(harness.workspaceDir, scenario.outputDir)
  const outputTarget = join(batchDir, 'outputs', scenario.outputDir)
  let error: string | null = null
  let files: string[] = []
  let finalAnswer = ''
  let status = 'unknown'
  let visibleFeedbackMs: number | null = null
  let promptSentAt: number | null = null
  let runAbortedByWatchdog = false
  let layout: RealBusinessResult['layout'] = { issues: [] }
  let layoutSnapshot: RealBusinessResult['layout_snapshot'] = null
  const repairAttempts: string[] = []
  const screenshotErrors: string[] = []
  const captureEvidence = async (relativePath: string): Promise<void> => {
    try {
      screenshots.push(await harness.screenshot(relativePath))
    } catch (caught) {
      screenshotErrors.push(caught instanceof Error ? caught.message : String(caught))
    }
  }
  try {
    await captureEvidence(join('screenshots', `${scenario.id}-before.png`))
    const sent = await submitPrompt(harness, prompt, sessionId, scenario.timeoutMs, join(batchDir, 'screenshots', scenario.id), approvals)
    promptSentAt = sent.sentAt
    visibleFeedbackMs = sent.visibleFeedbackMs
    const finalCount = sent.finalCount
    const statusAfterSubmit = await harness.evaluate<string>(`(() => document.querySelector('[data-testid="session-${sessionId}"] .session-state')?.className.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/)?.[1] ?? 'unknown')()`)
    if (statusAfterSubmit === 'succeeded') {
      await waitFor(async () => await harness.evaluate<boolean>(`document.querySelectorAll('[data-testid="final-answer"]').length > ${sent.beforeFinalCount}`) ? true : null, 5_000, `${scenario.id} final answer render`)
    }
    finalAnswer = await harness.evaluate<string>('Array.from(document.querySelectorAll("[data-testid=\\"final-answer\\"] .timeline-prose")).at(-1)?.textContent ?? ""')
    status = await harness.evaluate<string>(`(() => document.querySelector('[data-testid="session-${sessionId}"] .session-state')?.className.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/)?.[1] ?? 'unknown')()`)
    await captureEvidence(join('screenshots', `${scenario.id}-terminal.png`))
    const snapshot = await harness.evaluate<any>(`(() => {
      // .timeline is inside a scroll container. Its document rect moves when
      // the transcript auto-scrolls and must not be compared with the fixed
      // header as if they were sibling layout boxes.
      const names = ['.chat-area', '[data-testid="composer"]', '.task-header', '.session-panel'];
      const elements = names.flatMap((selector) => { const node = document.querySelector(selector); if (!(node instanceof HTMLElement)) return []; const r = node.getBoundingClientRect(); return [{id: selector, left:r.left, top:r.top, right:r.right, bottom:r.bottom}]; });
      return { viewport:{width:innerWidth,height:innerHeight}, horizontalScroll:document.documentElement.scrollWidth-document.documentElement.clientWidth, elements };
    })()`)
    layoutSnapshot = snapshot
    layout = evaluateLayoutSnapshot(snapshot)
    if (layout.issues.length > 0) error = `layout issues: ${layout.issues.map((issue) => issue.kind).join(', ')}`
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught)
    // A watchdog stop is already a terminal performance finding. Sending
    // artifact-repair prompts after stopping the run would create additional
    // model/tool traffic, approvals, and misleading timing evidence. Repair
    // is only valid after a completed run whose artifact failed validation.
    runAbortedByWatchdog = /stopped through GUI|first model activity|silent interval|remained queued|approval state|approval storm|always-allow form|wall clock/i.test(error)
    try {
      status = await harness.evaluate<string>(`(() => document.querySelector('[data-testid="session-${sessionId}"] .session-state')?.className.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/)?.[1] ?? 'unknown')()`)
      finalAnswer = await harness.evaluate<string>('Array.from(document.querySelectorAll("[data-testid=\\"final-answer\\"] .timeline-prose")).at(-1)?.textContent ?? ""')
    } catch {}
    await captureEvidence(join('screenshots', `${scenario.id}-failure.png`))
  }
  files = copyTree(outputSource, outputTarget)
  let artifactError = await smokeArtifact(scenario, outputSource)
  files = copyTree(outputSource, outputTarget)
  persistPlayProbe(outputSource, batchDir, scenario.id)
  let terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
  let validationError = artifactError ?? terminalIssue
  const initialValidationError = validationError
  // A layout defect is a renderer regression, not an instruction to spend
  // more model/tool rounds repairing an artifact. If an artifact really is
  // invalid as well, allow one bounded repair pass and then revalidate.
  const layoutOnlyFailure = layout.issues.length > 0 && artifactError === null && terminalIssue === null
  const missingDocs = /missing /i.test(artifactError ?? '')
  const missingOutput = /output directory was not created/i.test(artifactError ?? '')
  const maxRepairAttempts = layoutOnlyFailure ? 0 : scenario.artifactKind === 'spring-mysql' ? 8 : scenario.id === 'T03' ? 3 : (missingDocs || missingOutput) ? 2 : 1
  if (validationError !== null) error = error ?? validationError
  for (let attempt = 1; validationError !== null && attempt <= maxRepairAttempts; attempt += 1) {
    if (taskWallClockIssue(Date.now() - startedAt) !== null) break
    // One write-now repair is still valid after a silence stop: T06/T09 often
    // already have partial files, and T08's missing CSV is a one-shot write.
    if (runAbortedByWatchdog && attempt > 1) break
    if (/mysql schema reset failed|mysql schema reset skipped/i.test(validationError)) break
    const missingFiles = (() => {
      const selected = selectMissingFileRepair(scenario.id, validationError ?? '', files)
      if (selected.length > 0) return selected
      if (/output directory was not created/i.test(validationError ?? '')) {
        if (scenario.artifactKind === 'spring-mysql') return []
        if (scenario.id === 'T03') return ['index.html', 'admin.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md']
        if (scenario.id === 'T04') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'budget.csv']
        if (scenario.id === 'T06') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'data.csv']
        if (scenario.id === 'T07') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'tco.csv']
        if (scenario.id === 'T08') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv']
        return scenario.artifactKind === 'web' ? ['index.html', 'README.md', 'TEST-REPORT.md'] : ['README.md', 'TEST-REPORT.md']
      }
      if (scenario.id === 'T03') return []
      return []
    })()
    const repairBody = missingFiles.length > 0
      ? buildMissingFileRepairPrompt(scenario.outputDir, missingFiles, validationError ?? '')
      : buildArtifactRepairPrompt(scenario, validationError)
    const repairPrompt = `Repair attempt ${attempt} of ${maxRepairAttempts}.\n\n${repairBody}`
    repairAttempts.push(repairPrompt)
    try {
      await submitPrompt(
        harness,
        repairPrompt,
        sessionId,
        Math.min(scenario.timeoutMs, 8 * 60 * 1000),
        join(batchDir, 'screenshots', scenario.id, `repair-${attempt}`),
        approvals
      )
      finalAnswer = await harness.evaluate<string>('Array.from(document.querySelectorAll("[data-testid=\\"final-answer\\"] .timeline-prose")).at(-1)?.textContent ?? ""')
      status = await harness.evaluate<string>(`(() => document.querySelector('[data-testid="session-${sessionId}"] .session-state')?.className.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/)?.[1] ?? 'unknown')()`)
      files = copyTree(outputSource, outputTarget)
      artifactError = await smokeArtifact(scenario, outputSource)
      files = copyTree(outputSource, outputTarget)
      persistPlayProbe(outputSource, batchDir, scenario.id)
      terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
      validationError = artifactError ?? terminalIssue
      error = validationError
    } catch (caught) {
      const stopped = caught instanceof Error ? caught.message : String(caught)
      if (/stopped through GUI|first model activity|silent interval|remained queued|approval state|approval storm|always-allow form|wall clock/i.test(stopped)) {
        runAbortedByWatchdog = true
      }
      try {
        files = copyTree(outputSource, outputTarget)
        artifactError = await smokeArtifact(scenario, outputSource)
        files = copyTree(outputSource, outputTarget)
        persistPlayProbe(outputSource, batchDir, scenario.id)
        terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
        validationError = artifactError ?? terminalIssue
        error = validationError ?? stopped
      } catch {
        artifactError = stopped
        error = stopped
      }
    }
  }
  files = copyTree(outputSource, outputTarget)
  try {
    artifactError = await smokeArtifact(scenario, outputSource)
    files = copyTree(outputSource, outputTarget)
    persistPlayProbe(outputSource, batchDir, scenario.id)
    terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
    validationError = artifactError ?? terminalIssue
  } catch {}
  if (validationError !== null) error = validationError
  else if (layout.issues.length > 0) error = `layout issues: ${layout.issues.map((issue) => issue.kind).join(', ')}`
  else error = null
  if (error === null && status !== 'succeeded') status = 'succeeded'
  const allLines = await harness.evaluate<string[]>('window.__rxyRealProtocol ?? []')
  const messages = parseProtocol(allLines)
  // The performance clock starts at Enter/submit, not at the optional
  // preflight screenshot. A bounded CDP screenshot timeout must be reported
  // separately and cannot become a false first-token delay.
  const timing = eventTiming(messages, promptSentAt ?? startedAt, sessionId)
  // The prompt submission path records this before any model work. Keep it
  // separate from first-event timing so renderer latency is measurable.
  timing.visible_feedback_ms = visibleFeedbackMs
  const defects: string[] = []
  for (const screenshotError of screenshotErrors) defects.push(`screenshot evidence failed: ${screenshotError}`)
  if (screenshotErrors.length > 0) error = error ?? 'required GUI screenshot evidence was unavailable'
  if (timing.first_event_ms !== null && timing.first_event_ms > 15_000) defects.push(`first event ${timing.first_event_ms}ms exceeds 15s performance gate`)
  if (timing.first_event_ms !== null && timing.first_event_ms > 30_000) defects.push(`first event ${timing.first_event_ms}ms exceeds 30s hard-fail gate`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 8_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 8s target`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 15_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 15s performance gate`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 30_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 30s hard-fail gate`)
  for (const gap of timing.silent_gaps_ms) defects.push(`silent interval ${gap}ms exceeds 10s observation threshold`)
  const tools = await harness.evaluate<string[]>(`Array.from(document.querySelectorAll('[data-testid^="timeline-tool-"] .activity-label')).map((node) => node.textContent ?? '')`)
  const skillEvents = messages.filter((message) => String(message.method ?? '').toLowerCase().includes('skill')).map((message) => String(message.method))
  const mcpEvents = messages.filter((message) => String(message.method ?? '').toLowerCase().includes('mcp')).map((message) => String(message.method))
  if (scenario.id === 'T03' && skillEvents.length === 0 && !tools.some((tool) => tool.toLowerCase().includes('skill'))) defects.push('T03 did not expose a Skill search/load event')
  if (timing.first_token_ms !== null && firstTokenHardFail(timing.first_token_ms, timing.first_event_ms)) error = error ?? 'first token exceeded 30s hard-fail gate'
  // Research-first tasks (T03/T06/T08) show tools immediately, then wait on the
  // model between writes. Those gaps stay in defects; hard-fail only when the
  // GUI never showed real work in the first 30s (same waiver as firstTokenHardFail).
  if (timing.silent_gaps_ms.some((gap) => gap > 30_000) && (timing.first_event_ms === null || timing.first_event_ms > 30_000)) {
    error = error ?? 'silent interval exceeded 30s hard-fail gate'
  }
  const storm = approvalStormIssue(approvals.length)
  if (storm !== null) {
    defects.push(storm)
    error = error ?? storm
  }
  const wallIssue = taskWallClockIssue(timing.wall_ms)
  if (wallIssue !== null) {
    defects.push(wallIssue)
    error = error ?? wallIssue
  }
  const protocolFile = join(batchDir, 'events', `${scenario.id}.ndjson`)
  mkdirSync(dirname(protocolFile), { recursive: true })
  writeFileSync(protocolFile, allLines.join('\n') + '\n')
  const domFile = join(batchDir, 'dom', `${scenario.id}.json`)
  mkdirSync(dirname(domFile), { recursive: true })
  writeFileSync(domFile, JSON.stringify(await harness.domSnapshot(), null, 2))
  return {
    id: scenario.id,
    batch,
    title: scenario.title,
    prompt,
    model,
    provider: REAL_BUSINESS_PROVIDER,
    gateway,
    session_id: sessionId,
    status,
    final_answer: finalAnswer,
    output_dir: outputTarget,
    files,
    artifact_kind: scenario.artifactKind,
    usage: protocolUsage(messages),
    timing,
    approvals,
    tools,
    skill_events: skillEvents,
    mcp_events: mcpEvents,
    layout,
    layout_snapshot: layoutSnapshot,
    screenshots,
    protocol_file: protocolFile,
    dom_file: domFile,
    cleanup: null,
    defects,
    repair_attempts: repairAttempts,
    error
  }
}

async function runCliScenario(
  harness: CliAppserverHarness,
  scenario: RealBusinessScenario,
  batch: Batch,
  prompt: string,
  sessionId: string,
  model: string,
  gateway: string,
  batchDir: string,
  permissionMode: 'auto_edit' | 'full_auto'
): Promise<RealBusinessResult> {
  const startedAt = Date.now()
  const outputSource = join(harness.workspaceDir, scenario.outputDir)
  const outputTarget = join(batchDir, 'outputs', scenario.outputDir)
  let error: string | null = null
  let files: string[] = []
  let finalAnswer = ''
  let status = 'unknown'
  let visibleFeedbackMs: number | null = null
  let promptSentAt: number | null = null
  let runAbortedByWatchdog = false
  const repairAttempts: string[] = []
  const promptBudgetMs = Math.max(60_000, scenario.timeoutMs)
  try {
    const sent = await harness.prompt(sessionId, prompt, promptBudgetMs, permissionMode)
    promptSentAt = sent.sentAt
    visibleFeedbackMs = sent.visibleFeedbackMs
    finalAnswer = sent.text
    status = sent.status
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught)
    runAbortedByWatchdog = /RPC timeout|timed out|stalled|degraded|wall clock/i.test(error)
    try { await harness.interrupt(sessionId) } catch {}
  }
  files = copyTree(outputSource, outputTarget)
  let artifactError = await smokeArtifact(scenario, outputSource)
  files = copyTree(outputSource, outputTarget)
  persistPlayProbe(outputSource, batchDir, scenario.id)
  let terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
  let validationError = artifactError ?? terminalIssue
  const maxRepairAttempts = scenario.artifactKind === 'spring-mysql' || scenario.id === 'T09' ? 8 : scenario.id === 'T03' ? 3 : (/missing /i.test(artifactError ?? '') || /output directory was not created/i.test(artifactError ?? '')) ? 2 : 1
  if (validationError !== null) error = error ?? validationError
  for (let attempt = 1; validationError !== null && attempt <= maxRepairAttempts; attempt += 1) {
    if (taskWallClockIssue(Date.now() - startedAt) !== null) break
    if (runAbortedByWatchdog && attempt > 1) break
    const missingFiles = (() => {
      const selectedFiles = selectMissingFileRepair(scenario.id, validationError ?? '', files)
      if (selectedFiles.length > 0) return selectedFiles
      if (/output directory was not created/i.test(validationError ?? '')) {
        if (scenario.id === 'T03') return ['index.html', 'admin.html', 'PLAN.md', 'README.md', 'TEST-REPORT.md']
        if (scenario.id === 'T04') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'budget.csv']
        if (scenario.id === 'T06') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'data.csv']
        if (scenario.id === 'T07') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'tco.csv']
        if (scenario.id === 'T08') return ['index.html', 'README.md', 'TEST-REPORT.md', 'sources.md', 'areas.csv']
        return scenario.artifactKind === 'web' ? ['index.html', 'README.md', 'TEST-REPORT.md'] : ['README.md', 'TEST-REPORT.md']
      }
      return []
    })()
    const repairBody = missingFiles.length > 0
      ? buildMissingFileRepairPrompt(scenario.outputDir, missingFiles, validationError ?? '')
      : buildArtifactRepairPrompt(scenario, validationError)
    const repairPrompt = `Repair attempt ${attempt} of ${maxRepairAttempts}.\n\n${repairBody}`
    repairAttempts.push(repairPrompt)
    try {
      const repaired = await harness.prompt(sessionId, repairPrompt, Math.min(promptBudgetMs, 8 * 60 * 1000), permissionMode)
      finalAnswer = repaired.text
      status = repaired.status
      files = copyTree(outputSource, outputTarget)
      artifactError = await smokeArtifact(scenario, outputSource)
      files = copyTree(outputSource, outputTarget)
      persistPlayProbe(outputSource, batchDir, scenario.id)
      terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
      validationError = artifactError ?? terminalIssue
      error = validationError
    } catch (caught) {
      const stopped = caught instanceof Error ? caught.message : String(caught)
      if (/RPC timeout|timed out|stalled|degraded|wall clock/i.test(stopped)) runAbortedByWatchdog = true
      error = error ?? stopped
      break
    }
  }
  files = copyTree(outputSource, outputTarget)
  try {
    artifactError = await smokeArtifact(scenario, outputSource)
    files = copyTree(outputSource, outputTarget)
    persistPlayProbe(outputSource, batchDir, scenario.id)
    terminalIssue = terminalOutcomeIssue(status, finalAnswer, artifactError === null)
    validationError = artifactError ?? terminalIssue
  } catch {}
  if (validationError !== null) error = validationError
  else error = null
  if (error === null && status !== 'succeeded') status = 'succeeded'
  const messages = parseProtocol(harness.protocolLines)
  const timing = eventTiming(messages, promptSentAt ?? startedAt, sessionId)
  timing.visible_feedback_ms = visibleFeedbackMs
  const defects: string[] = []
  if (timing.first_event_ms !== null && timing.first_event_ms > 15_000) defects.push(`first event ${timing.first_event_ms}ms exceeds 15s performance gate`)
  if (timing.first_event_ms !== null && timing.first_event_ms > 30_000) defects.push(`first event ${timing.first_event_ms}ms exceeds 30s hard-fail gate`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 8_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 8s target`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 15_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 15s performance gate`)
  if (timing.first_token_ms !== null && timing.first_token_ms > 30_000) defects.push(`first token ${timing.first_token_ms}ms exceeds 30s hard-fail gate`)
  for (const gap of timing.silent_gaps_ms) defects.push(`silent interval ${gap}ms exceeds 10s observation threshold`)
  const tools = messages
    .filter((message) => String(message.method ?? '') === 'event/tool_begin')
    .map((message) => String(message.params?.tool_name ?? ''))
    .filter(Boolean)
  const skillEvents = messages.filter((message) => String(message.method ?? '').toLowerCase().includes('skill') || String(message.params?.tool_name ?? '').toLowerCase().includes('skill')).map((message) => String(message.method ?? message.params?.tool_name ?? ''))
  const mcpEvents = messages.filter((message) => String(message.method ?? '').toLowerCase().includes('mcp')).map((message) => String(message.method))
  if (scenario.id === 'T03' && skillEvents.length === 0 && !tools.some((tool) => tool.toLowerCase().includes('skill'))) defects.push('T03 did not expose a Skill search/load event')
  if (timing.first_token_ms !== null && firstTokenHardFail(timing.first_token_ms, timing.first_event_ms)) error = error ?? 'first token exceeded 30s hard-fail gate'
  if (timing.silent_gaps_ms.some((gap) => gap > 30_000) && (timing.first_event_ms === null || timing.first_event_ms > 30_000)) {
    error = error ?? 'silent interval exceeded 30s hard-fail gate'
  }
  const storm = approvalStormIssue(harness.approvals.length)
  if (storm !== null) {
    defects.push(storm)
    error = error ?? storm
  }
  const wallIssue = taskWallClockIssue(timing.wall_ms)
  if (wallIssue !== null) {
    defects.push(wallIssue)
    error = error ?? wallIssue
  }
  const protocolFile = join(batchDir, 'events', `${scenario.id}.ndjson`)
  mkdirSync(dirname(protocolFile), { recursive: true })
  writeFileSync(protocolFile, harness.protocolLines.join('\n') + '\n')
  const domFile = join(batchDir, 'dom', `${scenario.id}.json`)
  mkdirSync(dirname(domFile), { recursive: true })
  writeFileSync(domFile, JSON.stringify({ surface: 'cli', stderr: harness.stderr.slice(-80) }, null, 2))
  return {
    id: scenario.id,
    batch,
    title: scenario.title,
    prompt,
    model,
    provider: REAL_BUSINESS_PROVIDER,
    gateway,
    session_id: sessionId,
    status,
    final_answer: finalAnswer,
    output_dir: outputTarget,
    files,
    artifact_kind: scenario.artifactKind,
    usage: protocolUsage(messages),
    timing,
    approvals: [...harness.approvals],
    tools,
    skill_events: skillEvents,
    mcp_events: mcpEvents,
    layout: { issues: [] },
    layout_snapshot: null,
    screenshots: [],
    protocol_file: protocolFile,
    dom_file: domFile,
    cleanup: null,
    defects,
    repair_attempts: repairAttempts,
    error
  }
}

async function runCliBatch(batch: Batch): Promise<{ results: RealBusinessResult[]; cleanup: CleanupProof[] }> {
  const batchDir = join(artifactRoot, `batch-${batch}`)
  mkdirSync(batchDir, { recursive: true })
  const results: RealBusinessResult[] = []
  const cleanups: CleanupProof[] = []
  const permissionMode: 'auto_edit' | 'full_auto' = batch === 'B' ? 'full_auto' : 'auto_edit'
  const promptMap = new Map(
    (batch === 'A' ? prompts.independent : prompts.sequential).map((item) => [item.id, item.prompt])
  )
  if (batch === 'A') {
    for (const scenario of selected) {
      console.error(`[real-business] cli ${batch} ${scenario.id} start`)
      const harness = new CliAppserverHarness({ artifactDir: batchDir, extraEnv: desktopSuiteEnv() })
      const prompt = promptMap.get(scenario.id) ?? scenario.prompt
      let sessionId = ''
      let selectedModel = { model: REAL_BUSINESS_MODEL_ID, gateway: REAL_BUSINESS_GATEWAY }
      try {
        await harness.start()
        selectedModel = await harness.selectOpenCodeGoModel()
        sessionId = await harness.createSession(selectedModel.model)
        results.push(await runCliScenario(harness, scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, permissionMode))
      } catch (caught) {
        results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
      } finally {
        const cleanup = await harness.cleanup()
        cleanups.push(cleanup)
        const last = results.at(-1)
        if (last !== undefined && last.id === scenario.id) last.cleanup = cleanup
        console.error(`[real-business] cli ${batch} ${scenario.id} done status=${last?.status ?? 'unknown'} error=${last?.error ?? 'null'}`)
      }
    }
    writeFileSync(join(batchDir, 'results.json'), JSON.stringify({ batch, surface: 'cli', results, cleanup: cleanups }, null, 2))
    return { results, cleanup: cleanups }
  }
  const harness = new CliAppserverHarness({ artifactDir: batchDir, extraEnv: desktopSuiteEnv() })
  let sessionId = ''
  let selectedModel = { model: REAL_BUSINESS_MODEL_ID, gateway: REAL_BUSINESS_GATEWAY }
  try {
    await harness.start()
    selectedModel = await harness.selectOpenCodeGoModel()
    sessionId = await harness.createSession(selectedModel.model)
    for (const scenario of selected) {
      const prompt = promptMap.get(scenario.id) ?? scenario.prompt
      console.error(`[real-business] cli ${batch} ${scenario.id} start`)
      try {
        results.push(await runCliScenario(harness, scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, permissionMode))
      } catch (caught) {
        results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
      }
      const last = results.at(-1)
      console.error(`[real-business] cli ${batch} ${scenario.id} done status=${last?.status ?? 'unknown'} error=${last?.error ?? 'null'}`)
    }
  } catch (caught) {
    for (const scenario of selected) {
      const prompt = promptMap.get(scenario.id) ?? scenario.prompt
      results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
    }
  } finally {
    const cleanup = await harness.cleanup()
    cleanups.push(cleanup)
    for (const result of results) result.cleanup = cleanup
  }
  writeFileSync(join(batchDir, 'results.json'), JSON.stringify({ batch, surface: 'cli', results, cleanup: cleanups }, null, 2))
  return { results, cleanup: cleanups }
}

async function runBatch(batch: Batch): Promise<{ results: RealBusinessResult[]; cleanup: CleanupProof[] }> {
  if (surface === 'cli') return runCliBatch(batch)
  const batchDir = join(artifactRoot, `batch-${batch}`)
  mkdirSync(batchDir, { recursive: true })
  const results: RealBusinessResult[] = []
  const cleanups: CleanupProof[] = []
  if (batch === 'A') {
    for (const scenario of selected) {
      console.error(`[real-business] ${batch} ${scenario.id} start`)
      const harness = new DesktopCdpHarness({
        artifactDir: batchDir,
        fakeAppserver: false,
        workspaceMode: 'empty',
        width: 1440,
        height: 900,
      extraEnv: desktopSuiteEnv()
      })
      let cleanup: CleanupProof | null = null
      const prompt = prompts.independent.find((item) => item.id === scenario.id)?.prompt ?? scenario.prompt
      let sessionId = ''
      let selectedModel = { model: REAL_BUSINESS_MODEL_ID, gateway: REAL_BUSINESS_GATEWAY }
      try {
        await harness.start()
        await harness.evaluate(PROTOCOL_CAPTURE_BOOTSTRAP)
        await selectOpenCodeGoModelInSettings(harness)
        sessionId = await createSession(harness)
        selectedModel = await assertOpenCodeGoModel(harness)
        await setPermission(harness, 'auto_edit')
        try {
          results.push(await runScenario(harness, scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir))
        } catch (caught) {
          results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
        }
      } catch (caught) {
        results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
      } finally {
        cleanup = await harness.cleanup()
        cleanups.push(cleanup)
        const last = results.at(-1)
        if (last !== undefined && last.id === scenario.id) last.cleanup = cleanup
        console.error(`[real-business] ${batch} ${scenario.id} done status=${last?.status ?? 'unknown'} error=${last?.error ?? 'null'}`)
      }
    }
  } else {
    const harness = new DesktopCdpHarness({
      artifactDir: batchDir,
      fakeAppserver: false,
      workspaceMode: 'empty',
      width: 1440,
      height: 900,
      extraEnv: desktopSuiteEnv()
    })
    const sequentialPrompts = new Map(prompts.sequential.map((item) => [item.id, item.prompt]))
    let sessionId = ''
    let selectedModel = { model: REAL_BUSINESS_MODEL_ID, gateway: REAL_BUSINESS_GATEWAY }
    try {
      await harness.start()
        await harness.evaluate(PROTOCOL_CAPTURE_BOOTSTRAP)
      await selectOpenCodeGoModelInSettings(harness)
      sessionId = await createSession(harness)
      selectedModel = await assertOpenCodeGoModel(harness)
      await setPermission(harness, 'full_auto')
      for (const scenario of selected) {
        const prompt = sequentialPrompts.get(scenario.id) ?? scenario.prompt
        console.error(`[real-business] ${batch} ${scenario.id} start`)
        try {
          results.push(await runScenario(harness, scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir))
        } catch (caught) {
          results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
        }
        const last = results.at(-1)
        console.error(`[real-business] ${batch} ${scenario.id} done status=${last?.status ?? 'unknown'} error=${last?.error ?? 'null'}`)
      }
    } catch (caught) {
      for (const scenario of selected) {
        const prompt = sequentialPrompts.get(scenario.id) ?? scenario.prompt
        results.push(failureResult(scenario, batch, prompt, sessionId, selectedModel.model, selectedModel.gateway, batchDir, caught))
      }
    } finally {
      const cleanup = await harness.cleanup()
      cleanups.push(cleanup)
      for (const result of results) result.cleanup = cleanup
    }
  }
  writeFileSync(join(batchDir, 'results.json'), JSON.stringify({ batch, results, cleanup: cleanups }, null, 2))
  return { results, cleanup: cleanups }
}

async function main(): Promise<void> {
  mkdirSync(artifactRoot, { recursive: true })
  const all: RealBusinessResult[] = []
  const cleanup: CleanupProof[] = []
  for (const batch of batches) {
    const completed = await runBatch(batch)
    all.push(...completed.results)
    cleanup.push(...completed.cleanup)
  }
  writeFileSync(join(artifactRoot, 'real-business-results.json'), JSON.stringify({
    generated_at: new Date().toISOString(),
    repository: repositoryDir,
    model: REAL_BUSINESS_MODEL_ID,
    gateway: REAL_BUSINESS_GATEWAY,
    batches,
    results: all,
    cleanup
  }, null, 2))
  const failures = all.filter((result) => result.error !== null || result.status !== 'succeeded' || (result.cleanup !== null && !result.cleanup.passed))
  console.log(JSON.stringify({ artifactRoot, count: all.length, failures: failures.map((item) => ({ id: item.id, batch: item.batch, error: item.error, status: item.status })) }, null, 2))
  if (failures.length > 0) process.exitCode = 1
}

void main().catch((error) => {
  console.error(error instanceof Error ? error.stack ?? error.message : String(error))
  process.exitCode = 1
})
