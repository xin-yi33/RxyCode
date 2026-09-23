#!/usr/bin/env node
/**
 * One paid-model Desktop acceptance probe.
 *
 * Unlike screenshot.mts and desktop-stress.mts this never enables the fake
 * appserver.  It drives the real Electron renderer over CDP, records a visual
 * loading/final state, and always kills the Electron process tree on exit.
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoDir = resolve(process.env.RXYCODE_REPO_DIR ?? resolve(appDir, '..', '..'))
const outputDir = resolve(process.argv[2] ?? join(repoDir, 'artifacts', 'real-gui-probe'))
const debugPort = 9371
const vite = join(appDir, 'node_modules', 'electron-vite', 'bin', 'electron-vite.js')
const profile = mkdtempSync(join(tmpdir(), 'rxycode-real-gui-'))
const prompt = process.env.RXYCODE_REAL_GUI_PROMPT ??
  '/fast In the current workspace, inspect appserver startup only. Use glob, then grep, then read; do not use web search and do not modify files. Return exactly three short bullets: path, evidence, risk.'
const approvePendingRequest = process.env.RXYCODE_REAL_GUI_APPROVE === 'true'
const minimumToolCards = Number(process.env.RXYCODE_REAL_GUI_MIN_TOOLS ?? '3')
const cancelAfterFirstTool = process.env.RXYCODE_REAL_GUI_CANCEL === 'true'
const verifySessionIsolation = process.env.RXYCODE_REAL_GUI_MULTI_SESSION === 'true'

const delay = (ms: number): Promise<void> => new Promise((resolveDelay) => setTimeout(resolveDelay, ms))

function extractTerminalMetrics(lines: string[]): Record<string, unknown> {
  const messages = lines.flatMap((line) => {
    if (!line.startsWith('stdout: ')) return []
    try { return [JSON.parse(line.slice('stdout: '.length)) as Record<string, any>] } catch { return [] }
  })
  const final = messages.findLast((message) => message.method === 'event/final')?.params
  const token = messages.findLast((message) => message.method === 'event/token_usage')?.params
  const promptResult = messages.findLast((message) =>
    typeof message.result === 'object' && message.result !== null && 'input_tokens' in message.result
  )?.result
  const source = final ?? promptResult ?? token ?? {}
  return {
    input_tokens: Number(source.input_tokens ?? token?.input_tokens ?? 0),
    output_tokens: Number(source.output_tokens ?? token?.output_tokens ?? 0),
    cache_hit_tokens: Number(source.cache_hit_tokens ?? token?.cache_hit_tokens ?? 0),
    cache_hit_rate: Number(source.cache_hit_rate ?? token?.cache_hit_rate ?? 0)
  }
}

async function waitFor<T>(probe: () => Promise<T | null>, timeoutMs: number, label: string): Promise<T> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const value = await probe()
    if (value !== null) return value
    await delay(150)
  }
  throw new Error(`timeout waiting for ${label}`)
}

async function main(): Promise<void> {
  const startedAt = Date.now()
  if (!existsSync(vite)) throw new Error(`electron-vite missing: ${vite}`)
  mkdirSync(outputDir, { recursive: true })
  const dev = spawn(process.execPath, [vite, 'dev', '--', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`], {
    cwd: appDir,
    env: {
      ...process.env,
      RXYCODE_REPO_DIR: repoDir,
      RXYCODE_DESKTOP_WIDTH: '1100',
      RXYCODE_DESKTOP_HEIGHT: '760'
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  })
  let ws: WebSocket | null = null
  try {
    const target = await waitFor(async () => {
      try {
        const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json() as Array<{ type: string; webSocketDebuggerUrl?: string }>
        return pages.find((page) => page.type === 'page')?.webSocketDebuggerUrl ?? null
      } catch { return null }
    }, 90_000, 'Electron CDP')
    ws = new WebSocket(target)
    await new Promise<void>((resolveOpen, rejectOpen) => {
      ws!.onopen = () => resolveOpen()
      ws!.onerror = () => rejectOpen(new Error('CDP connection failed'))
    })
    let sequence = 0
    const pending = new Map<number, (message: any) => void>()
    ws.onmessage = (event) => {
      const message = JSON.parse(String(event.data))
      if (message.id && pending.has(message.id)) {
        pending.get(message.id)!(message)
        pending.delete(message.id)
      }
    }
    const send = (method: string, params: unknown = {}): Promise<any> => new Promise((resolveSend, rejectSend) => {
      const id = ++sequence
      pending.set(id, (message) => message.error ? rejectSend(new Error(JSON.stringify(message.error))) : resolveSend(message.result))
      ws!.send(JSON.stringify({ id, method, params }))
    })
    const evaluate = async (expression: string): Promise<any> => {
      const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails))
      return result.result?.value
    }
    const has = (selector: string): Promise<boolean> => evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)}))`)
    const screenshot = async (name: string): Promise<void> => {
      const image = await send('Page.captureScreenshot', { format: 'png' })
      writeFileSync(join(outputDir, name), Buffer.from(image.data, 'base64'))
    }

    await evaluate(`(() => {
      window.__rxyProbeLogs = [];
      window.api.appserver.onLog((line) => window.__rxyProbeLogs.push('stderr: ' + line));
      window.api.appserver.onLine((line) => window.__rxyProbeLogs.push('stdout: ' + line));
    })()`)
    await waitFor(async () => (await has('[data-testid="composer-input"]:not(:disabled)')) ? true : null, 90_000, 'composer ready')
    const needsSession = await evaluate(`document.querySelector('[data-testid="composer-input"]:not(:disabled)') === null`)
    if (needsSession) {
      await evaluate(`document.querySelector('.new-session, [data-testid="new-session"]')?.click()`)
      await waitFor(async () => (await has('[data-testid="composer-input"]:not(:disabled)')) ? true : null, 20_000, 'new session')
    }
    await evaluate(`(() => {
      const textarea = document.querySelector('[data-testid="composer-input"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, ${JSON.stringify(prompt)});
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    })()`)
    await waitFor(async () => (await has('[data-testid="composer-send"]:not(:disabled), .send:not(:disabled)')) ? true : null, 5_000, 'enabled send button')
    await evaluate(`document.querySelector('[data-testid="composer-send"], .send').click()`)
    await waitFor(async () => (await has('[data-testid="composer-stop"], [data-testid="running-indicator"], .tool-activity')) ? true : null, 30_000, 'run start')
    if (approvePendingRequest) {
      try {
        await waitFor(async () => (await has('.approval-dialog .approve, [data-testid="approval-card"] [data-action="allow"]')) ? true : null, 60_000, 'real approval request')
      } catch (error) {
        await screenshot('01-approval-timeout.png')
        const diagnostics = await evaluate(`({
          body: document.body.innerText,
          logs: window.__rxyProbeLogs ?? []
        })`)
        writeFileSync(join(outputDir, 'approval-timeout.json'), JSON.stringify(diagnostics, null, 2))
        throw error
      }
      await screenshot('01-approval-real.png')
      await evaluate(`document.querySelector('.approval-dialog .approve, [data-testid="approval-card"] [data-action="allow"]').click()`)
      await waitFor(async () => !(await has('.approval-dialog .approve, [data-testid="approval-card"] [data-action="allow"]')) ? true : null, 30_000, 'real approval resolution')
    }
    try {
      await waitFor(async () => (await has('.tool-activity, .tool-card, [data-testid="final-answer"]')) ? true : null, 90_000, 'first real tool card or final')
    } catch (error) {
      const status = await evaluate('window.api.appserver.getStatus()')
      const diagnostics = await evaluate(`JSON.stringify({
        body: document.body.innerText,
        logs: window.__rxyProbeLogs ?? []
      })`)
      writeFileSync(
        join(outputDir, 'real-gui-failure.json'),
        JSON.stringify({ status, ...JSON.parse(diagnostics) }, null, 2)
      )
      throw error
    }
    if (cancelAfterFirstTool) {
      await evaluate(`document.querySelector('.composer .stop').click()`)
      try {
        await waitFor(async () => !(await has('.running-indicator')) ? true : null, 30_000, 'real cancellation')
      } catch (error) {
        await screenshot('02-cancel-timeout.png')
        const diagnostics = await evaluate(`({
          body: document.body.innerText,
          logs: window.__rxyProbeLogs ?? []
        })`)
        writeFileSync(join(outputDir, 'cancel-timeout.json'), JSON.stringify(diagnostics, null, 2))
        throw error
      }
      await screenshot('02-cancelled-real.png')
      const cancelled = await evaluate(`(() => ({
        running: Boolean(document.querySelector('.running-indicator')),
        tools: Array.from(document.querySelectorAll('.tool-card')).map((card) => card.className),
        final: Array.from(document.querySelectorAll('.message.assistant .message-text')).at(-1)?.textContent ?? ''
      }))()`)
      if (cancelled.running || !cancelled.tools.some((value) => value.includes('error'))) {
        throw new Error(`invalid real GUI cancellation state: ${JSON.stringify(cancelled)}`)
      }
      writeFileSync(join(outputDir, 'real-gui-result.json'), JSON.stringify({ prompt, cancelled, elapsed_ms: Date.now() - startedAt }, null, 2))
      console.log(`REAL_GUI_PROBE_OK ${outputDir}`)
      return
    }
    await screenshot('01-loading-real.png')
    await waitFor(async () => (await has('[data-testid="final-answer"]')) && !(await has('[data-testid="composer-stop"]')) ? true : null, 120_000, 'real completion')
    await delay(300)
    await screenshot('02-final-real.png')
    const snapshot = await evaluate(`(() => ({
      prompt: document.querySelector('.timeline .user-turn, [data-testid="task-timeline"]')?.textContent ?? '',
      final: document.querySelector('[data-testid="final-answer"]')?.textContent ?? '',
      tools: Array.from(document.querySelectorAll('.tool-activity')).map((card) => ({
        name: card.querySelector('.activity-label, .tool-name')?.textContent ?? '', className: card.className
      })),
      error: document.querySelector('.error-banner, .timeline-error')?.textContent ?? '',
      viewport: { width: innerWidth, height: innerHeight },
      shellScroll: { y: scrollY, height: document.documentElement.scrollHeight }
    }))()`)
    const lines = await evaluate('window.__rxyProbeLogs ?? []') as string[]
    const result = {
      prompt,
      elapsed_ms: Date.now() - startedAt,
      metrics: extractTerminalMetrics(lines),
      snapshot
    }
    writeFileSync(join(outputDir, 'real-gui-result.json'), JSON.stringify(result, null, 2))
    if (!snapshot.final || snapshot.error) throw new Error(`invalid real GUI terminal state: ${JSON.stringify(snapshot)}`)
    if (snapshot.tools.length < minimumToolCards) {
      throw new Error(`expected at least ${minimumToolCards} real tool cards: ${JSON.stringify(snapshot.tools)}`)
    }
    if (snapshot.tools.some((tool) => tool.className.includes('running'))) {
      throw new Error(`real GUI left a tool card in running state: ${JSON.stringify(snapshot.tools)}`)
    }
    if (snapshot.shellScroll.y !== 0 || snapshot.shellScroll.height > snapshot.viewport.height) {
      throw new Error(`desktop shell scrolled unexpectedly: ${JSON.stringify(snapshot.shellScroll)}`)
    }
    if (verifySessionIsolation) {
      await evaluate(`document.querySelector('.new-session').click()`)
      await waitFor(async () => (await evaluate(`document.querySelectorAll('.session-item').length >= 2`)) ? true : null, 15_000, 'second session')
      const second = await evaluate(`(() => ({
        messages: document.querySelectorAll('.message').length,
        tools: document.querySelectorAll('.tool-card').length,
        active: document.querySelector('.session-item.active')?.querySelector('.session-id')?.textContent ?? ''
      }))()`)
      if (second.messages !== 0 || second.tools !== 0) throw new Error(`new session leaked prior UI state: ${JSON.stringify(second)}`)
      await evaluate(`document.querySelectorAll('.session-item')[0].click()`)
      const restored = await waitFor(async () => (await evaluate(`document.querySelectorAll('.tool-card').length`)) >= minimumToolCards ? true : null, 10_000, 'first session restoration')
      if (!restored) throw new Error('first session did not restore its tool cards')
      await screenshot('03-session-isolation-real.png')
    }
    console.log(`REAL_GUI_PROBE_OK ${outputDir}`)
  } finally {
    ws?.close()
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(dev.pid), '/T', '/F'], { stdio: 'ignore' })
    else { try { process.kill(dev.pid, 'SIGKILL') } catch {} }
    await delay(300)
    try { rmSync(profile, { recursive: true, force: true, maxRetries: 3 }) } catch {}
  }
}

void main().catch((error) => {
  console.error(`REAL_GUI_PROBE_FAILED ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
  process.exitCode = 1
})
