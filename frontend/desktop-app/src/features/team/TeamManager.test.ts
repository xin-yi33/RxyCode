import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { SETTINGS_SECTIONS } from '../../lib/settingsSections.ts'
import { TeamSection, TEAM_AUTO_WARNING } from '../settings/TeamSection.ts'
import { TeamInstallPanel } from './TeamInstallPanel.ts'
import { TeamManager, probeTeam } from './TeamManager.ts'
import { TeamPicker } from './TeamPicker.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX28: team/* path A; picker/install/section exist; team settings unlocked', () => {
  const probe = probeTeam(schema)
  assert.equal(probe.path, 'A')
  assert.notEqual(SETTINGS_SECTIONS.find((section) => section.id === 'team')?.blocked, true)
  const picker = renderToStaticMarkup(
    createElement(TeamPicker, {
      groups: [{ id: 'g1', name: 'reviewers' }],
      teams: [{ id: 't1', name: 'review', groupId: 'g1', description: 'reviews diffs' }],
      onUse: () => undefined
    })
  )
  assert.match(picker, /data-testid="team-picker"/)
  assert.match(picker, /data-testid="team-group-list"/)
  assert.match(picker, /data-visual-state/)
  const install = renderToStaticMarkup(
    createElement(TeamInstallPanel, { groups: [{ id: 'g1', name: 'reviewers' }], onInstall: () => undefined })
  )
  assert.match(install, /data-testid="team-install-panel"/)
  assert.match(install, /data-step="confirm"/)
  const section = renderToStaticMarkup(
    createElement(TeamSection, { auto: false, onAutoChange: () => undefined })
  )
  assert.match(section, /data-testid="team-section"/)
  assert.match(TEAM_AUTO_WARNING, /3–15x/)
  const manager = renderToStaticMarkup(
    createElement(TeamManager, {
      groups: [{ id: 'g1', name: 'reviewers' }],
      onRename: () => undefined,
      onDelete: () => undefined,
      onInstall: () => undefined,
      onActivate: () => undefined
    })
  )
  assert.match(manager, /Set active/)
  assert.match(manager, /data-visual-state/)
})
