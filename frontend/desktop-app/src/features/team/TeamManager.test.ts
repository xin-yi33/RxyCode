import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { SETTINGS_SECTIONS } from '../../lib/settingsSections.ts'
import { TeamSection, TEAM_AUTO_WARNING } from '../settings/TeamSection.ts'
import { TEAM_HOOKS_WARNING, TEAM_PACK_HINT, TeamInstallPanel } from './TeamInstallPanel.ts'
import { TeamManager, probeTeam } from './TeamManager.ts'
import { TeamDetailCard, TeamPicker } from './TeamPicker.ts'
import { CREATE_TEAM_PROMPT } from './team.model.ts'

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
  assert.match(install, /data-step="source"/)
  assert.match(install, /team-install-source/)
  assert.match(install, new RegExp(TEAM_PACK_HINT.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  assert.match(TEAM_HOOKS_WARNING, /hooks/)
  assert.match(CREATE_TEAM_PROMPT, /team_install/)
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
  const detail = renderToStaticMarkup(
    createElement(TeamDetailCard, {
      team: {
        id: 't1',
        name: 'review',
        groupId: 'g1',
        description: 'reviews diffs',
        members: [
          { role: 'lead', displayName: '主理人', isLeader: true },
          { role: 'coder', displayName: '编码员', isLeader: false }
        ],
        stages: [{ name: 'review', role: 'lead' }],
        examplePrompts: ['试试这样问我']
      }
    })
  )
  assert.match(detail, /team-detail-members/)
  assert.match(detail, /主理人/)
  assert.match(detail, /team-detail-stages/)
  assert.match(detail, /试试这样问我/)
  const plusMenu = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/components/ComposerPlusMenu.tsx'),
    'utf8'
  )
  assert.match(plusMenu, /plus-summon-team/)
  assert.match(plusMenu, /plus-create-team/)
  const header = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/components/TaskHeader.tsx'),
    'utf8'
  )
  assert.match(header, /task-team-badge/)
  const inspector = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/components/TaskInspector.tsx'),
    'utf8'
  )
  assert.match(inspector, /team-activity/)
  assert.match(inspector, /AgentActivity/)
})
