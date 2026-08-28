#!/usr/bin/env node
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DesktopCdpHarness, repositoryDir, waitFor, type CleanupProof } from './cdp-harness.mts'
import { desktopCdScenarios, type DesktopCdScenario } from './desktop-cd-scenarios.mts'
import { emptyUsage, extractChildUsage, type UsageMetrics } from './desktop-cd-usage.mts'

type Mode = 'deterministic' | 'real'

interface ScenarioResult {
  id: string
  round: number
  mode: Mode
  title: string
  prompt: string
  model: string
  provider: string
  gateway: string
  status: string
  terminal_state: string | null
  final_answer: string
  sessions: string[]
  child_sessions: string[]
  tools: Array<{ name: string; status: string; summary: string }>
  mcp: string[]
  skills: string[]
  approvals: string[]
  files: string[]
  usage: UsageMetrics
  child_usage: UsageMetrics
  timing: {
    wall_ms: number
    queued_ms: number | null
    active_ms: number | null
    cancel_latency_ms: number | null
    overlap_ms: number | null
    serial_baseline_ms: number | null
    concurrency_ratio: number | null
  }
  performance_trace: Record<string, unknown>
  screenshots: string[]
  dom_snapshot: string
  event_log: string
  error: string | null
}

const scriptDir = dirname(fileURLToPath(import.meta.url))
const defaultArtifactRoot = resolve(scriptDir, '..', '..', '..', 'artifacts')
const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
const mode = (process.argv.find((arg) => arg.startsWith('--mode='))?.split('=')[1] ?? 'deterministic') as Mode
if (!['deterministic', 'real'].includes(mode)) throw new Error(`unsupported mode: ${mode}`)
const realScenarioTimeoutMs = 120_000
const rounds = Number(process.argv.find((arg) => arg.startsWith('--rounds='))?.split('=')[1] ?? (mode === 'deterministic' ? '3' : '1'))
const onlyIds = new Set(
  (process.argv.find((arg) => arg.startsWith('--only='))?.slice('--only='.length) ?? '')
    .split(',')
    .filter(Boolean)
)
const selectedScenarios = onlyIds.size === 0
  ? desktopCdScenarios
  : desktopCdScenarios.filter((scenario) => onlyIds.has(scenario.id))
const RUNNING_TOOL_SELECTOR = '[data-testid^="timeline-tool-"].running, [data-testid^="timeline-tool-"].recovering, .tool-activity.running, .tool-activity.recovering'
const SEND_READY_SELECTOR = '[data-testid="composer-send"]:not(:disabled), .send:not(:disabled)'
const SEND_CLICK_SELECTOR = '[data-testid="composer-send"], .send'
const STOP_CLICK_SELECTOR = '[data-testid="composer-stop"], .composer-send.stop, .composer .stop'
const APPROVE_SELECTOR = '.approval-dialog .approve, [data-testid="approval-card"] [data-action="allow"]'
const REJECT_SELECTOR = '.approval-dialog .reject, [data-testid="approval-card"] [data-action="deny"]'
const ACTIVE_RUN_STATES = new Set(['queued', 'running', 'approval'])

function sessionRunStateScript(sessionId?: string): string {
  const item =
    sessionId === undefined
      ? `document.querySelector('.session-item.active')`
      : `document.querySelector('[data-testid="session-${sessionId}"]')`
  return `(() => {
    const item = ${item};
    const run = item?.getAttribute('data-run-state');
    if (typeof run === 'string' && run !== '') return run;
    const visual = item?.querySelector('.status-indicator')?.getAttribute('data-status');
    if (visual === 'spin') return 'running';
    if (visual === 'dot') return 'succeeded';
    if (visual === 'error') return 'failed';
    if (visual === 'idle') return 'cancelled';
    const legacy = item?.querySelector('.session-state')?.className.match(/state-(queued|running|approval|succeeded|failed|cancelled|timed_out)/);
    return legacy?.[1] ?? null;
  })()`
}
const artifactRoot = resolve(
  process.argv.find((arg) => arg.startsWith('--artifacts='))?.slice('--artifacts='.length) ??
  join(defaultArtifactRoot, `desktop-cd-suite-${timestamp}`)
)

function token(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function extractUsage(messages: Array<Record<string, any>>, sessionIds: string[]): UsageMetrics {
  const belongs = (message: Record<string, any>): boolean =>
    sessionIds.includes(String(message.params?.session_id ?? ''))
  const tokenEvent = messages.findLast((message) => message.method === 'event/token_usage' && belongs(message))?.params
  const final = messages.findLast((message) => message.method === 'event/final' && belongs(message))?.params
  const source = tokenEvent ?? final
  if (source === undefined) {
    return emptyUsage()
  }
  const input = token(source.input_tokens)
  const cache = token(source.cache_hit_tokens)
  return {
    source: tokenEvent !== undefined ? 'token_event' : 'final',
    input_tokens: input,
    output_tokens: token(source.output_tokens),
    cache_hit_tokens: cache,
    cache_hit_rate: input !== null && input > 0 && cache !== null ? cache / input : null,
    reporting_status: source.reporting_status === 'reported' || source.reporting_status === 'partial'
      ? source.reporting_status
      : input !== null || token(source.output_tokens) !== null || cache !== null ? 'partial' : 'not_reported'
  }
}

function parseProtocol(lines: string[]): Array<Record<string, any>> {
  return lines.flatMap((line) => {
    try { return [JSON.parse(line) as Record<string, any>] } catch { return [] }
  })
}

function expectedStatusForScenario(scenario: DesktopCdScenario): string {
  return scenario.kind === 'failure'
    ? 'failed'
    : scenario.kind === 'cancel' || scenario.kind === 'child-cancel'
      ? 'cancelled'
      : 'succeeded'
}

function concurrencyEvidence(
  messages: Array<Record<string, any>>,
  sessionIds: string[],
  wallMs: number
): { overlapMs: number | null; serialBaselineMs: number | null; ratio: number | null } {
  const intervals = sessionIds.flatMap((sessionId) => {
    const values = messages
      .filter((message) => String(message.params?.session_id ?? '') === sessionId)
      .flatMap((message) => typeof message.__at_ms === 'number' ? [message.__at_ms] : [])
    return values.length > 1 ? [{ start: Math.min(...values), end: Math.max(...values) }] : []
  })
  if (intervals.length < 2) return { overlapMs: null, serialBaselineMs: null, ratio: null }
  const overlapMs = Math.max(
    0,
    Math.min(...intervals.map((interval) => interval.end)) -
      Math.max(...intervals.map((interval) => interval.start))
  )
  const serialBaselineMs = intervals.reduce(
    (sum, interval) => sum + interval.end - interval.start,
    0
  )
  return {
    overlapMs,
    serialBaselineMs,
    ratio: serialBaselineMs > 0 ? wallMs / serialBaselineMs : null
  }
}

async function setActiveModel(harness: DesktopCdpHarness, scenario: DesktopCdScenario, sequence: number): Promise<string> {
  const expectedGateway = scenario.model.startsWith('zen/')
    ? 'https://opencode.ai/zen/v1'
    : 'https://opencode.ai/zen/go/v1'
  if (mode !== 'real') return expectedGateway
  const id = 900000 + sequence
  const result = await harness.evaluate<{ ok?: boolean; id?: string }>(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { off(); reject(new Error('models/set_active timeout')); }, 30000);
    const off = window.api.appserver.onLine((line) => {
      try {
        const message = JSON.parse(line);
        if (message.id !== ${id}) return;
        clearTimeout(timeout); off();
        if (message.error) reject(new Error(message.error.message ?? 'models/set_active failed'));
        else resolve(message.result ?? {});
      } catch {}
    });
    window.api.appserver.sendLine(${JSON.stringify(JSON.stringify({
      jsonrpc: '2.0', id, method: 'models/set_active', params: { id: scenario.model }
    }))});
  })`)
  if (result.ok !== true || result.id !== scenario.model) {
    throw new Error(`model activation rejected for ${scenario.model}`)
  }
  const listId = id + 100000
  const listed = await harness.evaluate<{ active?: string; models?: Array<{ id?: string; base_url?: string }> }>(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { off(); reject(new Error('models/list timeout')); }, 30000);
    const off = window.api.appserver.onLine((line) => {
      try {
        const message = JSON.parse(line);
        if (message.id !== ${listId}) return;
        clearTimeout(timeout); off();
        if (message.error) reject(new Error(message.error.message ?? 'models/list failed'));
        else resolve(message.result ?? {});
      } catch {}
    });
    window.api.appserver.sendLine(${JSON.stringify(JSON.stringify({
      jsonrpc: '2.0', id: listId, method: 'models/list', params: {}
    }))});
  })`)
  const gateway = listed.models?.find((item) => item.id === scenario.model)?.base_url ?? ''
  if (listed.active !== scenario.model || gateway.replace(/\/$/, '') !== expectedGateway) {
    throw new Error(`model/gateway mismatch for ${scenario.model}: ${listed.active ?? 'none'} @ ${gateway || 'missing'}`)
  }
  return gateway.replace(/\/$/, '')
}

async function createSessionAndSubmit(
  harness: DesktopCdpHarness,
  prompt: string
): Promise<string> {
  const prior = await harness.evaluate<number>(`document.querySelectorAll('.session-item').length`)
  await harness.evaluate(`document.querySelector('.new-session:not(:disabled)')?.click()`)
  await waitFor(async () => {
    const count = await harness.evaluate<number>(`document.querySelectorAll('.session-item').length`)
    return count > prior ? true : null
  }, 20_000, 'new task session')
  const sessionId = await harness.evaluate<string>(
    `document.querySelector('.session-item.active .session-id')?.textContent ?? ''`
  )
  await harness.typePrompt(prompt)
  await waitFor(async () => (await harness.has(SEND_READY_SELECTOR)) ? true : null, 5_000, 'enabled send')
  await harness.evaluate(`document.querySelector(${JSON.stringify(SEND_CLICK_SELECTOR)})?.click()`)
  await waitFor(async () => (await harness.has('.running-indicator') || await harness.has(RUNNING_TOOL_SELECTOR)) ? true : null, 20_000, 'run start')
  return sessionId
}

async function createSessionOnly(harness: DesktopCdpHarness): Promise<string> {
  const prior = await harness.evaluate<number>('document.querySelectorAll(".session-item").length')
  await harness.evaluate('document.querySelector(".new-session:not(:disabled)")?.click()')
  await waitFor(async () => {
    const count = await harness.evaluate<number>('document.querySelectorAll(".session-item").length')
    return count > prior ? true : null
  }, 20_000, 'new parallel task')
  return harness.evaluate<string>('document.querySelector(".session-item.active .session-id")?.textContent ?? ""')
}

async function submitExistingSession(
  harness: DesktopCdpHarness,
  sessionId: string,
  prompt: string,
): Promise<void> {
  await selectSession(harness, sessionId)
  await harness.typePrompt(prompt)
  await waitFor(async () => (await harness.has(SEND_READY_SELECTOR)) ? true : null, 5_000, 'enabled parallel send')
  await harness.evaluate(`document.querySelector(${JSON.stringify(SEND_CLICK_SELECTOR)})?.click()`)
  await waitFor(async () => (await harness.has('.running-indicator') || await harness.has(RUNNING_TOOL_SELECTOR)) ? true : null, 20_000, 'parallel run start')
}

async function waitForSessionsTerminal(
  harness: DesktopCdpHarness,
  sessionIds: string[],
  timeoutMs: number,
  label: string
): Promise<void> {
  await waitFor(async () => {
    // A real model can request approval even when a scenario did not intend
    // to exercise writes (for example, a bash command classified as WRITE).
    // Reject unexpected approvals so the runner never waits forever. The
    // terminal-state assertion below records the scenario as a failure.
    if (await harness.has(REJECT_SELECTOR)) {
      await harness.evaluate(`document.querySelector(${JSON.stringify(REJECT_SELECTOR)})?.click()`)
      return null
    }
    return (await harness.evaluate<boolean>(`(() => {
      const ids = ${JSON.stringify(sessionIds)};
      const active = ${JSON.stringify([...ACTIVE_RUN_STATES])};
      return ids.every((id) => {
        const item = document.querySelector('[data-testid="session-' + id + '"]');
        const run = item?.getAttribute('data-run-state');
        if (typeof run === 'string' && run !== '') return !active.includes(run);
        const visual = item?.querySelector('.status-indicator')?.getAttribute('data-status');
        if (visual === 'spin') return false;
        if (visual === 'dot' || visual === 'error' || visual === 'idle') return true;
        const state = item?.querySelector('.session-state');
        return state !== null && !state.classList.contains('state-running') &&
          !state.classList.contains('state-queued') && !state.classList.contains('state-approval');
      });
    })()`)) ? true : null
  }, timeoutMs, label)
}

async function selectSession(harness: DesktopCdpHarness, sessionId: string): Promise<void> {
  await harness.evaluate(`document.querySelector('[data-testid="session-${sessionId}"]')?.click()`)
  await waitFor(async () => (await harness.evaluate<boolean>(
    `document.querySelector('.session-item.active .session-id')?.textContent === ${JSON.stringify(sessionId)}`
  )) ? true : null, 5_000, `select session ${sessionId}`)
}

async function runOne(
  harness: DesktopCdpHarness,
  scenario: DesktopCdScenario,
  round: number,
  protocolLines: string[],
  scenarioIndex: number
): Promise<ScenarioResult> {
  const started = Date.now()
  const protocolStart = protocolLines.length
  // Leading @agent mentions are executable Desktop syntax. Keep them at the
  // beginning instead of hiding them behind the report correlation prefix.
  const prompt = scenario.prompt.startsWith('@')
    ? scenario.prompt.replace(
        /^((?:@[a-z0-9][a-z0-9_-]*\s+)+)/,
        `$1[${scenario.id}] `
      )
    : `[${scenario.id}] ${scenario.prompt}`
  const screenshots: string[] = []
  const sessionIds: string[] = []
  let status = 'succeeded'
  let error: string | null = null
  let cancelStarted: number | null = null

  const activeGateway = await setActiveModel(harness, scenario, scenarioIndex + round * 100)
  try {
    if (scenario.kind === 'parallel-primary') {
      for (let index = 0; index < 4; index += 1) sessionIds.push(await createSessionOnly(harness))
      for (const [index, suffix] of ['protocol', 'accessibility', 'packaging', 'reliability'].entries()) {
        await submitExistingSession(harness, sessionIds[index]!, `${prompt}\nParallel audit lane: ${suffix}.`)
      }
      await waitForSessionsTerminal(
        harness, sessionIds, mode === 'real' ? realScenarioTimeoutMs : 60_000,
        `${scenario.id} parallel completion`
      )
    } else {
      const executionPrompt = scenario.kind === 'approval' || scenario.kind === 'child-approval'
        ? `${prompt}\napproval demo`
        : prompt
      sessionIds.push(await createSessionAndSubmit(harness, executionPrompt))
      if (scenario.kind === 'approval' || scenario.kind === 'child-approval') {
        await waitFor(async () => (await harness.has(APPROVE_SELECTOR)) ? true : null, mode === 'real' ? 120_000 : 30_000, `${scenario.id} approval`)
        screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/approval.png`))
        await harness.evaluate(`document.querySelector(${JSON.stringify(APPROVE_SELECTOR)})?.click()`)
      } else if (scenario.kind === 'cancel' || scenario.kind === 'child-cancel') {
        await harness.waitForSelector(RUNNING_TOOL_SELECTOR, 30_000)
        screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/running.png`))
        cancelStarted = Date.now()
        await harness.evaluate(`document.querySelector(${JSON.stringify(STOP_CLICK_SELECTOR)})?.click()`)
        status = 'cancelled'
      } else if (scenario.kind === 'busy') {
        await harness.typePrompt('duplicate submission must remain blocked')
        const hasSend = await harness.has(SEND_READY_SELECTOR)
        if (hasSend) throw new Error('duplicate send became enabled while the session was busy')
      }
      await waitForSessionsTerminal(
        harness, [sessionIds[0]!], mode === 'real' ? realScenarioTimeoutMs : 60_000,
        `${scenario.id} terminal state`
      )
      if (scenario.kind === 'failure') status = 'failed'
      if (scenario.kind === 'child-cancel') {
        const parentSessionId = sessionIds[0]!
        const sibling = await createSessionAndSubmit(
          harness,
          'Verify that an unrelated Primary session still completes after recursive cancellation.'
        )
        sessionIds.push(sibling)
        await waitForSessionsTerminal(
          harness, [sibling], mode === 'real' ? realScenarioTimeoutMs : 60_000,
          `${scenario.id} sibling completion`
        )
        await selectSession(harness, parentSessionId)
      }
    }

    if (sessionIds[0]) await selectSession(harness, sessionIds[0])
    if (scenario.id === 'DTS-17' && sessionIds[0]) {
      const taskId = sessionIds[0]
      await harness.evaluate(`document.querySelector('[data-testid="rename-task-${taskId}"]')?.click()`)
      await harness.waitForSelector(`[data-testid="rename-input-${taskId}"]`, 5_000)
      await harness.evaluate(`(() => {
        const input = document.querySelector('[data-testid="rename-input-${taskId}"]')
        if (!(input instanceof HTMLInputElement)) throw new Error('rename input missing')
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
        setter?.call(input, 'Theme diagnostics renamed')
        input.dispatchEvent(new Event('input', { bubbles: true }))
      })()`)
      await harness.evaluate(`document.querySelector('[data-testid="rename-save-${taskId}"]')?.click()`)
      await waitFor(async () => (await harness.evaluate<boolean>(`document.querySelector('[data-testid="session-${taskId}"] .session-title')?.textContent === 'Theme diagnostics renamed'`)) ? true : null, 5_000, 'task rename')
      await harness.evaluate(`document.querySelector('[data-testid="trash-task-${taskId}"]')?.click()`)
      await harness.waitForSelector('[data-testid="task-toast"]', 5_000)
      const activeDeleteMessage = await harness.evaluate<string>(`document.querySelector('[data-testid="task-toast"]')?.textContent ?? ''`)
      if (!activeDeleteMessage.includes('删不掉')) throw new Error('active task deletion was not rejected')
      const replacementTaskId = await createSessionOnly(harness)
      sessionIds.push(replacementTaskId)
      await harness.evaluate(`document.querySelector('[data-testid="trash-task-${taskId}"]')?.click()`)
      await waitFor(async () => (
        await harness.has(`[data-testid="session-recycle"] [data-testid="restore-task-${taskId}"]`)
      ) ? true : null, 5_000, 'recently deleted section')
      await harness.evaluate(
        `document.querySelector('[data-testid="session-recycle"] [data-testid="restore-task-${taskId}"]')?.click()`
      )
      await waitFor(async () => (
        await harness.has(`[data-testid="session-${taskId}"]:not([disabled])`)
      ) ? true : null, 5_000, 'restored task visible')
      await selectSession(harness, taskId)
    }
    if (scenario.kind.includes('child')) {
      await harness.waitForSelector('[data-testid^="timeline-child-"]', mode === 'real' ? 120_000 : 30_000)
      const clickedChild = await harness.evaluate<boolean>(`(() => {
        const child = document.querySelector('[data-testid^="timeline-child-"]')
        child?.click()
        return child !== null
      })()`)
      if (!clickedChild) throw new Error('child session row was not clickable')
      await harness.waitForSelector('[data-testid="inspector"]', 5_000)
      await harness.waitForSelector('[data-testid^="child-timeline-"]', 5_000)
      await harness.waitForSelector('[data-testid="usage-panel"]', 5_000)
      screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/child-inspector.png`))
    } else if (scenario.id === 'DTS-29') {
      await harness.waitForSelector('[data-testid^="timeline-recovery-"]', 5_000)
      await harness.evaluate(`document.querySelector('[data-testid^="timeline-recovery-"] summary')?.click()`)
      await harness.waitForSelector('[data-testid="inspector"]', 5_000)
      await harness.waitForSelector('[data-testid="usage-panel"]', 5_000)
      screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/recovery-inspector.png`))
    }
    screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/terminal.png`))
    if (scenario.id === 'DTS-29') {
      for (const view of [
        { name: 'wide', width: 1440, height: 900 },
        { name: 'standard', width: 1280, height: 720 },
        { name: 'drawer', width: 1024, height: 768 },
        { name: 'compact', width: 800, height: 700 }
      ]) {
        for (const theme of ['light', 'dark'] as const) {
          for (const zoom of [1, 1.25, 1.5]) {
            await harness.setViewport(view.width, view.height)
            await harness.setZoom(zoom)
            await harness.evaluate(`document.documentElement.dataset.theme = ${JSON.stringify(theme)}`)
            screenshots.push(await harness.screenshot(
              `screenshots/round-${round}/${scenario.id}/${view.name}-${theme}-${String(zoom).replace('.', '-')}.png`
            ))
          }
        }
      }
      await harness.setViewport(1440, 900)
      await harness.setZoom(1)
      await harness.evaluate(`document.documentElement.dataset.theme = 'system'`)
    }
  } catch (caught) {
    status = 'failed'
    error = caught instanceof Error ? caught.message : String(caught)
    if (await harness.has('.running-indicator') || await harness.has(RUNNING_TOOL_SELECTOR)) {
      await harness.evaluate(`document.querySelector(${JSON.stringify(STOP_CLICK_SELECTOR)})?.click()`)
      try {
        await waitFor(async () => (!(await harness.has('.running-indicator')) && !(await harness.has(RUNNING_TOOL_SELECTOR))) ? true : null,
          15_000, `${scenario.id} failure cleanup`)
      } catch {}
    }
    screenshots.push(await harness.screenshot(`screenshots/round-${round}/${scenario.id}/failure.png`))
  }

  const snapshot = await harness.evaluate<{
    final: string
    terminalState: string | null
    tools: Array<{ name: string; status: string; summary: string }>
    childSessions: string[]
    shellOverflow: boolean
    nestedHorizontalOverflow: boolean
    runningTools: number
  }>(`(() => ({
    // The command-center renderer deliberately does not render Final Answer as
    // a chat bubble. Keep the legacy selector as a compatibility fallback for
    // older Desktop builds, but make the stable data-testid the source of
    // truth for the current timeline.
    final: document.querySelector('[data-testid="final-answer"] .timeline-prose')?.textContent ??
      document.querySelector('.message.assistant .message-text')?.textContent ?? '',
    terminalState: ${sessionRunStateScript()},
    tools: Array.from(document.querySelectorAll('[data-testid^="timeline-tool-"]')).map((card) => ({
      name: card.querySelector('.activity-label')?.textContent ?? '',
      status: card.classList.contains('running') || card.classList.contains('recovering') ? 'running' : card.classList.contains('error') ? 'error' : 'ok',
      summary: card.querySelector('.activity-result')?.textContent ?? ''
    })),
    childSessions: Array.from(document.querySelectorAll('[data-testid^="timeline-child-"]')).map((node) => node.textContent ?? ''),
    shellOverflow: scrollY !== 0 || document.documentElement.scrollWidth > document.documentElement.clientWidth || document.documentElement.scrollHeight > document.documentElement.clientHeight,
    nestedHorizontalOverflow: Array.from(document.querySelectorAll('.session-panel, .task-inspector, .chat-column')).some((node) => node.scrollWidth > node.clientWidth + 1),
    runningTools: document.querySelectorAll('[data-testid^="timeline-tool-"].running, [data-testid^="timeline-tool-"].recovering').length
  }))()`)
  if (snapshot.shellOverflow) {
    error = error ?? 'desktop shell overflowed instead of scrolling independent panes'
    status = 'failed'
  }
  if (snapshot.nestedHorizontalOverflow) {
    error = error ?? 'a desktop pane overflowed horizontally instead of clipping or scrolling internally'
    status = 'failed'
  }
  if (snapshot.runningTools > 0) {
    error = error ?? 'terminal snapshot retained a running tool card'
    status = 'failed'
  }
  const expectedStatus = expectedStatusForScenario(scenario)
  if (snapshot.terminalState !== null && snapshot.terminalState !== expectedStatus) {
    error = error ?? `GUI terminal state mismatch: expected ${expectedStatus}, received ${snapshot.terminalState}`
    status = 'failed'
  }

  const dom = await harness.domSnapshot()
  const domPath = join(harness.artifactDir, `dom/round-${round}/${scenario.id}.json`)
  mkdirSync(dirname(domPath), { recursive: true })
  writeFileSync(domPath, JSON.stringify(dom, null, 2))
  const allProtocol = await harness.evaluate<string[]>(`window.__rxyCdProtocol ?? []`)
  const scenarioProtocol = allProtocol.slice(protocolStart)
  const eventPath = join(harness.artifactDir, `events/round-${round}/${scenario.id}.ndjson`)
  mkdirSync(dirname(eventPath), { recursive: true })
  writeFileSync(eventPath, scenarioProtocol.join('\n') + '\n')
  const messages = parseProtocol(scenarioProtocol)
  if (scenario.id === 'DTS-29') {
    const methods = messages.map((message) => String(message.method ?? ''))
    const failedTool = methods.indexOf('event/tool_end')
    const recoveryStarted = methods.indexOf('event/recovery_started')
    const recoveryResolved = methods.indexOf('event/recovery_resolved')
    const finalEvent = methods.indexOf('event/final')
    if (recoveryStarted < 0 || recoveryResolved < 0 || finalEvent < 0 || recoveryStarted < failedTool || recoveryResolved < recoveryStarted || finalEvent < recoveryResolved) {
      error = error ?? 'recovery events were missing or appeared out of chronological order'
      status = 'failed'
    }
  }
  const times = messages.flatMap((message) => typeof message.__at_ms === 'number' ? [message.__at_ms] : [])
  const childSessions = messages
    .filter((message) => String(message.method ?? '').startsWith('child_session/'))
    .map((message) => String(message.params?.session_id ?? ''))
    .filter(Boolean)
  const elapsed = Date.now() - started
  const concurrency = scenario.kind === 'parallel-primary'
    ? concurrencyEvidence(messages, sessionIds, elapsed)
    : { overlapMs: null, serialBaselineMs: null, ratio: null }
  return {
    id: scenario.id,
    round,
    mode,
    title: scenario.title,
    prompt,
    model: scenario.model,
    provider: scenario.model.split('/')[0] ?? '',
    gateway: activeGateway,
    status,
    terminal_state: snapshot.terminalState,
    final_answer: snapshot.final,
    sessions: sessionIds,
    child_sessions: [...new Set(childSessions.length > 0 ? childSessions : snapshot.childSessions)],
    tools: snapshot.tools,
    mcp: snapshot.tools.filter((tool) => tool.name.toLowerCase().includes('mcp')).map((tool) => tool.name),
    skills: snapshot.tools.filter((tool) => tool.name.toLowerCase().includes('skill')).map((tool) => tool.name),
    approvals: scenario.kind.includes('approval') ? ['approved through Desktop dialog'] : [],
    files: [],
    usage: extractUsage(messages, sessionIds),
    child_usage: extractChildUsage(messages),
    timing: {
      wall_ms: elapsed,
      queued_ms: null,
      active_ms: times.length > 1 ? Math.max(...times) - Math.min(...times) : elapsed,
      cancel_latency_ms: cancelStarted === null ? null : Date.now() - cancelStarted,
      overlap_ms: concurrency.overlapMs,
      serial_baseline_ms: concurrency.serialBaselineMs,
      concurrency_ratio: concurrency.ratio
    },
    performance_trace: {},
    screenshots,
    dom_snapshot: domPath,
    event_log: eventPath,
    error
  }
}

async function runRound(round: number): Promise<{ results: ScenarioResult[]; cleanup: CleanupProof }> {
  const roundDir = join(artifactRoot, mode, `round-${round}`)
  const harness = new DesktopCdpHarness({
    artifactDir: roundDir,
    fakeAppserver: mode === 'deterministic',
    width: 1440,
    height: 900,
    extraEnv: mode === 'real' ? {
      RXYCODE_SUBAGENTS: '1',
      RXYCODE_SUBAGENTS_TASK: '1',
      RXYCODE_SUBAGENTS_MENTION: '1',
      RXYCODE_SUBAGENTS_CHILD_TASKS: '1'
    } : {}
  })
  const results: ScenarioResult[] = []
  const protocolLines: string[] = []
  let cleanup: CleanupProof | null = null
  try {
    await harness.start()
    await harness.evaluate(`(() => {
      window.__rxyCdProtocol = [];
      window.__rxyCdAppserverLogs = [];
      window.api.appserver.onLog((line) => window.__rxyCdAppserverLogs.push(line));
      window.api.appserver.onLine((line) => {
        try {
          const message = JSON.parse(line);
          message.__at_ms = performance.now();
          window.__rxyCdProtocol.push(JSON.stringify(message));
        } catch { window.__rxyCdProtocol.push(line); }
      });
    })()`)
    await harness.waitForSelector('.new-session:not(:disabled)', 90_000)
    for (const scenario of selectedScenarios) {
      const index = desktopCdScenarios.findIndex((candidate) => candidate.id === scenario.id)
      const before = await harness.evaluate<string[]>(`window.__rxyCdProtocol ?? []`)
      protocolLines.splice(0, protocolLines.length, ...before)
      const result = await runOne(harness, scenario, round, protocolLines, index)
      const after = await harness.evaluate<string[]>(`window.__rxyCdProtocol ?? []`)
      protocolLines.splice(0, protocolLines.length, ...after)
      // Rebuild evidence for this result from the actual post-run protocol slice.
      const messages = parseProtocol(after.slice(before.length))
      result.usage = extractUsage(messages, result.sessions)
      result.child_usage = extractChildUsage(messages)
      result.performance_trace = await harness.evaluate<Record<string, unknown>>(
        'window.__rxyDesktopPerformance ?? { activeSessionId: null, sessions: {} }'
      )
      result.child_sessions = [...new Set(messages
        .filter((message) => String(message.method ?? '').startsWith('child_session/'))
        .map((message) => String(message.params?.session_id ?? ''))
        .filter(Boolean))]
      const expectedStatus = expectedStatusForScenario(scenario)
      if (result.status !== expectedStatus) {
        result.error = result.error ?? `expected ${expectedStatus}, received ${result.status}`
      }
      const expectsChildren = index >= 20
      if (expectsChildren && result.child_sessions.length === 0) {
        result.error = result.error ?? 'scenario required protocol-backed child sessions but observed none'
      }
      if (
        mode === 'deterministic' &&
        scenario.kind === 'parallel-primary' &&
        (result.timing.overlap_ms === null || result.timing.overlap_ms <= 0 ||
          result.timing.concurrency_ratio === null || result.timing.concurrency_ratio >= 0.7)
      ) {
        result.error = result.error ?? 'parallel execution missed the measured overlap/ratio gate'
      }
      if (
        mode === 'real' && scenario.kind === 'parallel-primary' &&
        (result.timing.overlap_ms === null || result.timing.overlap_ms <= 0)
      ) {
        result.error = result.error ?? 'real Primary sessions did not produce overlapping event intervals'
      }
      if (
        mode === 'deterministic' &&
        expectedStatus === 'succeeded' &&
        !scenario.kind.includes('approval') &&
        !result.final_answer.includes(scenario.id)
      ) {
        result.error = result.error ?? 'final answer did not correlate to the scenario id'
      }
      results.push(result)
      console.log(`${mode} round=${round} ${scenario.id} ${result.status}`)
    }
    writeFileSync(join(roundDir, 'results.json'), JSON.stringify(results, null, 2))
  } finally {
    cleanup = await harness.cleanup()
  }
  if (!cleanup.passed) throw new Error(`cleanup proof failed: ${JSON.stringify(cleanup)}`)
  return { results, cleanup }
}

async function main(): Promise<void> {
  mkdirSync(artifactRoot, { recursive: true })
  const allResults: ScenarioResult[] = []
  const cleanups: CleanupProof[] = []
  for (let round = 1; round <= rounds; round += 1) {
    const completed = await runRound(round)
    allResults.push(...completed.results)
    cleanups.push(completed.cleanup)
  }
  const expected = selectedScenarios.length * rounds
  if (allResults.length !== expected) throw new Error(`expected ${expected} results, got ${allResults.length}`)
  const unexpected = allResults.filter((result) => result.error !== null)
  writeFileSync(join(artifactRoot, `${mode}-results.json`), JSON.stringify({
    generated_at: new Date().toISOString(),
    repository: repositoryDir,
    mode,
    rounds,
    results: allResults,
    cleanup: cleanups
  }, null, 2))
  if (unexpected.length > 0) {
    throw new Error(`unexpected scenario failures: ${unexpected.map((item) => `${item.id}: ${item.error}`).join('; ')}`)
  }
  console.log(`DESKTOP_CD_SUITE_OK ${artifactRoot}`)
}

void main().catch((error) => {
  console.error(`DESKTOP_CD_SUITE_FAILED ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
  process.exitCode = 1
})
