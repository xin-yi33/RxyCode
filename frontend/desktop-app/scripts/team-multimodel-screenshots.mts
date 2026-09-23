#!/usr/bin/env node
/** Capture WorkBuddy-style team + multi-model settings screenshots. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { DesktopCdpHarness } from './cdp-harness.mts'

const artifactDir = process.env.RXYCODE_GUI_ARTIFACTS ?? join(process.cwd(), 'artifacts', `team-mm-${Date.now()}`)
mkdirSync(artifactDir, { recursive: true })

async function main(): Promise<void> {
  const harness = new DesktopCdpHarness({
    artifactDir,
    fakeAppserver: true,
    width: 1440,
    height: 900
  })
  try {
    await harness.start()
    await harness.waitForSelector('.desktop-navigation-panel .new-session:not(:disabled)', 60_000)
    await harness.evaluate(`document.querySelector('.desktop-navigation-panel .new-session:not(:disabled)')?.click()`)
    await harness.waitForSelector('[data-testid="composer-plus"]:not(:disabled)', 20_000)
    await harness.evaluate(`document.querySelector('[data-testid="composer-plus"]')?.click()`)
    await harness.waitForSelector('[data-testid="plus-summon-team"]', 5_000)
    await harness.screenshot('plus-root-summon.png')
    await harness.evaluate(`document.querySelector('[data-testid="plus-summon-team"]')?.click()`)
    await harness.waitForSelector('[data-testid="plus-create-team"]', 5_000)
    await harness.screenshot('plus-summon-submenu.png')
    await harness.evaluate(`document.querySelector('[data-testid="plus-summon-software_dev"]')?.click()`)
    await harness.waitForSelector('[data-testid="plus-team-detail"]', 5_000)
    await harness.screenshot('plus-team-detail.png')
    await harness.evaluate(`document.querySelector('[data-testid="plus-summon-use"]')?.click()`)
    await harness.waitForSelector('[data-testid="task-team-badge"]', 8_000)
    await harness.screenshot('task-header-badge.png')
    const settingsProbe = await harness.evaluate<{ entry: boolean; dialog: boolean }>(`({
      entry: Boolean(document.querySelector('.settings-entry')),
      dialog: Boolean(document.querySelector('[data-testid="settings-dialog"]'))
    })`)
    if (!settingsProbe.entry) throw new Error(`settings-entry missing: ${JSON.stringify(settingsProbe)}`)
    await harness.evaluate(`document.querySelector('.settings-entry')?.click()`)
    await harness.waitForSelector('[data-testid="settings-dialog"]', 8_000)
    await harness.evaluate(`document.querySelector('[data-tab="team"]')?.click()`)
    await harness.waitForSelector('[data-testid="settings-team"]', 8_000)
    await harness.waitForSelector('[data-testid="agents-settings"]', 5_000)
    await harness.screenshot('settings-team-folded.png')
    await harness.evaluate(`document.querySelector('[data-testid="agents-enabled"]')?.click()`)
    await harness.waitForSelector('[data-testid="agents-params"]', 3_000)
    await harness.evaluate(`document.querySelector('[data-testid="multi-model-enabled"]')?.click()`)
    await harness.waitForSelector('[data-testid="multi-model-roles"]', 3_000)
    await harness.screenshot('settings-team-multimodel.png')
    writeFileSync(
      join(artifactDir, 'index.json'),
      JSON.stringify({ artifactDir, shots: ['plus-root-summon.png', 'plus-summon-submenu.png', 'plus-team-detail.png', 'task-header-badge.png', 'settings-team-folded.png', 'settings-team-multimodel.png'] }, null, 2)
    )
  } finally {
    await harness.cleanup()
  }
}

void main().catch((error) => {
  console.error(error)
  process.exit(1)
})
