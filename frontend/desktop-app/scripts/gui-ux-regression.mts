#!/usr/bin/env node
/** Focused real-Electron regression suite for the Desktop shell. */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { DesktopCdpHarness, waitFor } from './cdp-harness.mts'

const artifactDir = process.env.RXYCODE_GUI_ARTIFACTS ?? join(process.cwd(), 'artifacts', `gui-ux-${Date.now()}`)
mkdirSync(artifactDir, { recursive: true })

async function main(): Promise<void> {
  const harness = new DesktopCdpHarness({
    artifactDir,
    fakeAppserver: true,
    width: 1440,
    height: 900
  })
  let cleaned = false
  const pendingRpc = async (): Promise<number> => harness.evaluate<number>(`Number((document.querySelector('[data-testid="diagnostics-pending-rpc"]')?.textContent ?? '').match(/\\d+/)?.[0] ?? 0)`)
  const results: Array<{ id: string; status: 'passed' | 'failed'; detail?: string }> = []
  const check = async (id: string, action: () => Promise<void>): Promise<void> => {
    try {
      await action()
      results.push({ id, status: 'passed' })
    } catch (error) {
      results.push({ id, status: 'failed', detail: error instanceof Error ? error.message : String(error) })
    }
  }
  try {
    await harness.start()
    await harness.evaluate(`(() => {
      window.__rxyGuiUxLines = [];
      window.api.appserver.onLine((line) => window.__rxyGuiUxLines.push(line));
    })()`)
    const rail = '.desktop-navigation-panel'
    const activeSessionIdJs = `(document.querySelector('${rail} .session-item.active')?.getAttribute('data-testid') ?? '').replace(/^session-/, '')`
    await harness.waitForSelector(`${rail} .new-session:not(:disabled)`, 60_000)
    await harness.evaluate(`document.querySelector('${rail} .new-session:not(:disabled)')?.click()`)
    await harness.waitForSelector('[data-testid="composer-input"]:not(:disabled)', 20_000)

    await check('UX-01 composer structure', async () => {
      if (!(await harness.has('[data-testid="composer-surface"]'))) throw new Error('Codex-like composer surface missing')
      if (!(await harness.has('[data-testid="composer-send"]'))) throw new Error('send arrow missing')
      if (!(await harness.has('[data-testid="composer-permission-mode"]'))) throw new Error('task permission switch missing')
      const emptyLayout = await harness.evaluate<{ borderStyle: string; center: number; columnCenter: number }>(`(() => {
        const empty = document.querySelector('.chat-empty')
        const column = document.querySelector('.task-main')
        if (!(empty instanceof HTMLElement) || !(column instanceof HTMLElement)) throw new Error('empty task surface missing')
        const rect = empty.getBoundingClientRect()
        const columnRect = column.getBoundingClientRect()
        return {
          borderStyle: getComputedStyle(empty).borderStyle,
          center: (rect.left + rect.right) / 2,
          columnCenter: (columnRect.left + columnRect.right) / 2
        }
      })()`)
      if (emptyLayout.borderStyle === 'dashed') throw new Error('empty task still uses a boxed placeholder')
      if (Math.abs(emptyLayout.center - emptyLayout.columnCenter) > 48) throw new Error(`empty task is not centered in the task column: ${JSON.stringify(emptyLayout)}`)
      const startupStatus = await harness.evaluate<string | null>(`document.querySelector('[data-testid="task-startup-status"]')?.textContent ?? null`)
      if (startupStatus !== null) throw new Error(`idle task retained a stale startup banner: ${startupStatus}`)
      await harness.screenshot('layout-empty.png')
    })
    await check('UX-01b first turn exposes startup progress', async () => {
      await harness.typePrompt('startup demo')
      await harness.pressKey('Enter')
      await harness.waitForSelector('[data-testid="running-indicator"]', 2_000)
      const startup = await harness.evaluate<{ phase: string; text: string }>(`(() => {
        const node = document.querySelector('[data-testid="running-indicator"]')
        return { phase: node?.getAttribute('data-phase') ?? '', text: node?.textContent ?? '' }
      })()`)
      if (startup.phase !== 'startup') throw new Error(`first turn was not marked startup: ${JSON.stringify(startup)}`)
      if (!startup.text.includes('Starting') && !startup.text.includes('启动')) throw new Error(`startup progress missing: ${startup.text}`)
      await waitFor(async () => (await harness.has('[data-testid="running-indicator"]')) ? null : true, 5_000, 'startup task terminal')
    })
    await check('UX-02 Enter submits', async () => {
      await harness.typePrompt('enter sends a real task')
      await harness.pressKey('Enter')
      await harness.waitForSelector('[data-testid="composer-stop"]', 10_000)
      await waitFor(async () => (await harness.has('[data-testid="composer-stop"]')) ? null : true, 20_000, 'Enter task terminal')
    })
    await check('UX-02b recoverable stall reconnects before the next turn', async () => {
      await harness.typePrompt('timeout demo')
      await harness.pressKey('Enter')
      await harness.waitForSelector('[data-testid^="timeline-recovery-"]', 10_000)
      const recovered = await harness.evaluate<string>(`document.querySelector('[data-testid^="timeline-recovery-"] .activity-label')?.textContent ?? ''`)
      if (!recovered.includes('auto') && !recovered.includes('reconnect') && !recovered.includes('恢复')) {
        throw new Error(`recoverable stall was not rendered as recovery: ${recovered}`)
      }
      if (await harness.has('.timeline-error')) throw new Error('intermediate transport stall became a final error')
      const finalCountBeforeRetry = await harness.evaluate<number>(`document.querySelectorAll('[data-testid="final-answer"]').length`)
      await harness.typePrompt('after timeout reconnect')
      await harness.pressKey('Enter')
      await waitFor(async () => (await harness.evaluate<number>(`document.querySelectorAll('[data-testid="final-answer"]').length`)) > finalCountBeforeRetry ? true : null, 10_000, 'post-reconnect final answer')
    })
    await check('UX-02c recovery survives switching to another task', async () => {
      const previousId = await harness.evaluate<string>(activeSessionIdJs)
      await harness.evaluate(`document.querySelector('${rail} .new-session:not(:disabled)')?.click()`)
      await waitFor(async () => {
        const nextId = await harness.evaluate<string>(activeSessionIdJs)
        return nextId !== '' && nextId !== previousId ? true : null
      }, 3_000, 'task after recovered timeout')
      await harness.typePrompt('new task after recovered timeout')
      await harness.pressKey('Enter')
      await waitFor(async () => (await harness.has('[data-testid="final-answer"]')) ? true : null, 10_000, 'new task final answer after recovery')
      if (await harness.has('.timeline-error')) throw new Error('new task inherited the previous degraded error')
    })
    await check('UX-03 approval closes after decision', async () => {
      await harness.typePrompt('approval demo')
      await harness.pressKey('Enter')
      const approvalReady = `document.querySelector('.approval-dialog .approve, [data-testid="approval-card"] [data-action="allow"]')`
      try {
        await waitFor(async () => (await harness.has('.approval-dialog .approve') || await harness.has('[data-testid="approval-card"] [data-action="allow"]')) ? true : null, 20_000, 'approval card or dialog')
      } catch (error) {
        const debug = await harness.evaluate(`(() => ({
          composerDisabled: document.querySelector('[data-testid="composer-input"]')?.disabled ?? null,
          composerValue: document.querySelector('[data-testid="composer-input"]')?.value ?? '',
          timeline: document.querySelector('[data-testid="task-timeline"]')?.textContent ?? '',
          pending: document.querySelector('[data-testid="diagnostics-pending-rpc"]')?.textContent ?? '',
          card: document.querySelector('[data-testid="approval-card"]')?.textContent ?? ''
        }))()`)
        throw new Error(`${error instanceof Error ? error.message : String(error)} debug=${JSON.stringify(debug)} lines=${JSON.stringify(await harness.evaluate('window.__rxyGuiUxLines ?? []'))}`)
      }
      await harness.evaluate(`${approvalReady}?.click()`)
      await waitFor(async () => (await harness.has('.approval-dialog') || await harness.has('[data-testid="approval-card"] [data-action="allow"]')) ? null : true, 2_000, 'approval UI close')
      await waitFor(async () => (await harness.has('[data-testid="composer-stop"]')) ? null : true, 20_000, 'approved task terminal')
      await waitFor(async () => {
        const pending = await harness.evaluate<number>(`Number((document.querySelector('[data-testid="diagnostics-pending-rpc"]')?.textContent ?? '').match(/\\d+/)?.[0] ?? 0)`)
        return pending === 0 ? true : null
      }, 5_000, 'approval RPC reconciliation')
    })
    await check('UX-04 light theme uses semantic light surfaces', async () => {
      await harness.evaluate(`document.documentElement.dataset.theme = 'light'`)
      const colors = await harness.evaluate<{ body: string; composer: string }>(`(() => ({
        body: getComputedStyle(document.body).backgroundColor,
        composer: getComputedStyle(document.querySelector('.composer-surface')).backgroundColor
      }))()`)
      if (colors.body === 'rgb(17, 19, 24)' || colors.composer === 'rgb(17, 19, 24)') throw new Error(`dark surface leaked into light theme: ${JSON.stringify(colors)}`)
      await harness.evaluate(`document.querySelector('.settings-button')?.click()`)
      await harness.waitForSelector('.settings-page', 2_000)
      const settingsSurface = await harness.evaluate<string>(`getComputedStyle(document.querySelector('.settings-page')).backgroundColor`)
      if (settingsSurface === 'rgb(31, 32, 37)' || settingsSurface === 'rgb(17, 19, 24)') throw new Error(`dark dialog leaked into light theme: ${settingsSurface}`)
      await harness.evaluate(`document.querySelector('.settings-close')?.click()`)
      await harness.evaluate(`document.documentElement.dataset.theme = 'dark'`)
    })
    await check('UX-05 full access requires confirmation', async () => {
      await harness.evaluate(`(() => { const select = document.querySelector('[data-testid="composer-permission-mode"]'); if (!(select instanceof HTMLSelectElement)) throw new Error('permission selector missing'); select.value = 'full_auto'; select.dispatchEvent(new Event('change', { bubbles: true })); })()`)
      await harness.waitForSelector('#full-auto-title', 2_000)
      await harness.evaluate(`document.querySelector('.confirm-actions button')?.click()`)
      if (await harness.has('#full-auto-title')) throw new Error('confirmation did not close')
    })
    await check('UX-06 settings closes with Escape', async () => {
      await harness.evaluate(`document.querySelector('.settings-button')?.click()`)
      await harness.waitForSelector('.settings-page', 2_000)
      await harness.pressKey('Escape')
      await waitFor(async () => (await harness.has('.settings-page')) ? null : true, 2_000, 'settings close')
      await waitFor(async () => (await pendingRpc()) === 0 ? true : null, 5_000, 'settings RPC reconciliation')
    })
    await check('UX-06b goal dialog closes with Escape', async () => {
      await harness.evaluate(`document.querySelector('[data-testid="composer-plus"]')?.click()`)
      await harness.waitForSelector('[data-testid="composer-plus-menu"]', 2_000)
      await harness.evaluate(`document.querySelector('[data-testid="plus-goal"]')?.click()`)
      await harness.waitForSelector('[data-testid="goal-dialog"]', 2_000)
      await harness.pressKey('Escape')
      await waitFor(async () => (await harness.has('[data-testid="goal-dialog"]')) ? null : true, 2_000, 'goal dialog Escape close')
    })
    await check('UX-07 delete is optimistic', async () => {
      const taskId = await harness.evaluate<string>(activeSessionIdJs)
      const started = Date.now()
      await harness.evaluate(`document.querySelector('${rail} [data-testid="trash-task-${taskId}"]')?.click()`)
      await harness.waitForSelector('[data-testid="task-toast"]', 2_000)
      const feedback = await harness.evaluate<string>(`document.querySelector('[data-testid="task-toast"]')?.textContent ?? ''`)
      if (!feedback.includes('正在打开')) throw new Error(`active task was not protected: ${feedback}`)
      if (!(await harness.has(`${rail} .session-item.active`))) throw new Error('active task disappeared after delete')
      if (Date.now() - started > 1_000) throw new Error('active-task protection was not immediate')
    })
    await check('UX-08 default layout keeps a persistent left rail and centers the task column', async () => {
      const layout = await harness.evaluate<{
        columns: string
        inspector: boolean
        railDisplay: string
        columnCenter: number
        timelineCenter: number
        composerCenter: number
      }>(`(() => {
        const node = document.querySelector('.command-layout')
        const railNode = document.querySelector('.desktop-navigation-panel')
        const column = document.querySelector('.task-main')
        const timeline = document.querySelector('.timeline')
        const composer = document.querySelector('[data-testid="composer-surface"]')
        if (!(node instanceof HTMLElement) || !(railNode instanceof HTMLElement) || !(column instanceof HTMLElement) || !(timeline instanceof HTMLElement) || !(composer instanceof HTMLElement)) throw new Error('command layout geometry missing')
        const center = (element) => {
          const rect = element.getBoundingClientRect()
          return (rect.left + rect.right) / 2
        }
        return {
          columns: getComputedStyle(node).gridTemplateColumns,
          inspector: document.querySelector('.contextual-inspector-slot') !== null,
          railDisplay: getComputedStyle(railNode).display,
          columnCenter: center(column),
          timelineCenter: center(timeline),
          composerCenter: center(composer)
        }
      })()`)
      if (layout.inspector) throw new Error('inspector is open by default')
      if (layout.railDisplay === 'none') throw new Error('desktop rail is hidden')
      const tracks = layout.columns.trim().split(/\s+/).filter(Boolean)
      if (tracks.length !== 2) throw new Error(`desktop workbench should be rail + task: ${layout.columns}`)
      if (!tracks[0].startsWith('248')) throw new Error(`left rail is not 248px: ${layout.columns}`)
      if (Math.abs(layout.timelineCenter - layout.columnCenter) > 48) throw new Error(`timeline is not centered in the task column: ${JSON.stringify(layout)}`)
      if (Math.abs(layout.composerCenter - layout.columnCenter) > 48) throw new Error(`composer is not centered in the task column: ${JSON.stringify(layout)}`)
      const composerWidth = await harness.evaluate<number>(`document.querySelector('[data-testid="composer-surface"]')?.getBoundingClientRect().width ?? 0`)
      if (composerWidth > 800) throw new Error(`composer is wider than the Codex-style command surface: ${composerWidth}`)
      await harness.screenshot('layout-default.png')
    })
    await check('UX-09 timeline keeps tool results before Final Answer', async () => {
      const order = await harness.evaluate<string[]>(`Array.from(document.querySelectorAll('[data-testid="task-timeline"] > *')).map((node) => {
        if (node.classList.contains('timeline-prompt')) return 'prompt'
        if (node.classList.contains('tool-activity')) return 'tool'
        if (node.classList.contains('final-answer')) return 'final'
        if (node.classList.contains('timeline-assistant')) return 'assistant'
        return 'other'
      })`)
      const promptIndex = order.indexOf('prompt')
      const toolIndex = order.indexOf('tool')
      const finalIndex = order.lastIndexOf('final')
      if (promptIndex < 0 || toolIndex < 0 || finalIndex < 0 || !(promptIndex < toolIndex && toolIndex < finalIndex)) {
        throw new Error(`timeline order is not chronological: ${order.join(' > ')}`)
      }
    })
    await check('UX-10 narrow window keeps drawers out of the default grid', async () => {
      await harness.setViewport(800, 700)
      const layout = await harness.evaluate<{ columns: string; navigation: string }>(`(() => {
        const node = document.querySelector('.command-layout')
        const nav = document.querySelector('.desktop-navigation-panel')
        if (!(node instanceof HTMLElement) || !(nav instanceof HTMLElement)) throw new Error('responsive shell missing')
        return { columns: getComputedStyle(node).gridTemplateColumns, navigation: getComputedStyle(nav).display }
      })()`)
      if (layout.columns.trim().split(/\\s+/).length > 1) throw new Error(`narrow layout reserves a column: ${layout.columns}`)
      if (layout.navigation !== 'none') throw new Error(`narrow layout keeps permanent navigation: ${layout.navigation}`)
      await harness.evaluate(`document.querySelector('.nav-toggle')?.click()`)
      await harness.waitForSelector('.nav-sheet.open', 2_000)
      await harness.pressKey('Escape')
      await waitFor(async () => (await harness.has('.nav-sheet.open')) ? null : true, 2_000, 'navigation drawer Escape close')
      await harness.setViewport(1440, 900)
    })
    await check('UX-11 usage reports unknown values explicitly', async () => {
      const tool = await harness.evaluate<string>(`document.querySelector('.activity-inspect-button')?.textContent ?? ''`)
      if (tool === '') throw new Error('tool inspector affordance missing')
      await harness.evaluate(`document.querySelector('.activity-inspect-button')?.click()`)
      await harness.waitForSelector('[data-testid="usage-panel"]', 2_000)
      const usage = await harness.evaluate<string>(`document.querySelector('[data-testid="usage-panel"]')?.textContent ?? ''`)
      if (!usage.includes('not reported')) throw new Error(`unknown usage was not explicit: ${usage}`)
      await harness.evaluate(`document.querySelector('[data-testid="inspector"] .inspector-header button')?.click()`)
      await waitFor(async () => (await harness.has('.contextual-inspector-slot')) ? null : true, 2_000, 'usage inspector close')
    })
    await check('UX-12 non-active task delete and restore give immediate feedback', async () => {
      const originalId = await harness.evaluate<string>(activeSessionIdJs)
      await harness.evaluate(`document.querySelector('${rail} .new-session')?.click()`)
      await waitFor(async () => {
        const next = await harness.evaluate<string>(activeSessionIdJs)
        return next !== '' && next !== originalId ? true : null
      }, 3_000, 'second task creation')
      const secondId = await harness.evaluate<string>(activeSessionIdJs)
      await harness.evaluate(`document.querySelector('${rail} [data-testid="session-${originalId}"]')?.click()`)
      await harness.waitForSelector(`${rail} .session-item.active`, 2_000)
      await harness.evaluate(`document.querySelector('${rail} [data-testid="trash-task-${secondId}"]')?.click()`)
      await waitFor(async () => (await harness.evaluate<string>(`document.querySelector('[data-testid="task-toast"]')?.textContent ?? ''`)).includes('已删除任务') ? true : null, 2_000, 'delete success toast')
      if (await harness.has(`${rail} [data-testid="session-category-recent"] [data-testid="session-${secondId}"]`)) {
        throw new Error('deleted task remained in active task list')
      }
      await harness.evaluate(`document.querySelector('${rail} [data-testid="open-settings"]')?.click()`)
      await harness.waitForSelector('[data-testid="settings-recycle"]', 2_000)
      await harness.evaluate(`document.querySelector('[data-tab="recycle"]')?.click()`)
      await harness.waitForSelector(`[data-testid="restore-task-${secondId}"]`, 2_000)
      await harness.evaluate(`document.querySelector('[data-testid="restore-task-${secondId}"]')?.click()`)
      await waitFor(async () => (await harness.evaluate<string>(`document.querySelector('[data-testid="task-toast"]')?.textContent ?? ''`)).includes('已恢复任务') ? true : null, 2_000, 'restore success toast')
      await harness.evaluate(`document.querySelector('.settings-close')?.click()`)
      await waitFor(async () => (await harness.has(`${rail} [data-testid="session-${secondId}"]`)) ? true : null, 2_000, 'restored task visible')
    })
    await check('UX-13 inspector opens only on demand from a tool activity', async () => {
      await harness.evaluate(`(() => { const details = document.querySelector('.tool-activity'); if (details instanceof HTMLDetailsElement) details.open = true; const button = details?.querySelector('.activity-inspect-button'); if (button instanceof HTMLElement) button.click(); })()`)
      await harness.waitForSelector('.contextual-inspector-slot', 2_000)
      if (!(await harness.has('[data-testid="inspector"]'))) throw new Error('task inspector content missing')
      await harness.screenshot('layout-inspector-open.png')
      await harness.evaluate(`document.querySelector('[data-testid="inspector"] .inspector-header button')?.click()`)
      await waitFor(async () => (await harness.has('.contextual-inspector-slot')) ? null : true, 2_000, 'inspector close')
    })
    await waitFor(async () => (await pendingRpc()) === 0 ? true : null, 5_000, 'all GUI RPCs settled').catch(async (error) => {
      console.error(`GUI_UX_PENDING ${JSON.stringify({ snapshot: await harness.domSnapshot(), lines: await harness.evaluate('window.__rxyGuiUxLines ?? []') })}`)
      throw error
    })
    await harness.screenshot('ux-final.png')
    const proof = await harness.cleanup()
    cleaned = true
    if (!proof.passed) throw new Error(`cleanup proof failed: ${JSON.stringify(proof)}`)
  } finally {
    // cleanup is idempotent and the final proof is still written when a case fails
    if (!cleaned) {
      try { await harness.cleanup() } catch (error) {
        console.error(`GUI_UX_CLEANUP_ERROR ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }
  const failed = results.filter((item) => item.status === 'failed')
  console.log(JSON.stringify({ artifactDir, results }, null, 2))
  if (failed.length > 0) process.exitCode = 1
}

void main()
