import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { effortOptionsFor, SETTINGS_ENTRY, SETTINGS_SECTIONS, TEAM_SECTION_ALIGN } from './settingsSections.ts'

test('H16: eight sections, lazy registry, team/recycle BLOCKED, effort from model', () => {
  assert.equal(SETTINGS_SECTIONS.length, 8)
  assert.equal(SETTINGS_SECTIONS.every((section) => section.lazy), true)
  assert.equal(SETTINGS_SECTIONS.find((s) => s.id === 'team')?.blocked, true)
  assert.equal(SETTINGS_SECTIONS.find((s) => s.id === 'recycle')?.blocked, true)
  assert.equal(SETTINGS_ENTRY.borderRadiusPx, 6)
  assert.deepEqual(effortOptionsFor({ effort_options: ['low', 'high'] }), ['low', 'high'])
  assert.deepEqual(effortOptionsFor({}), [])
  assert.match(TEAM_SECTION_ALIGN, /H10/)
})

test('H16 left-bottom settings entry CSS uses 6px radius and H15 hover', () => {
  const css = readFileSync(new URL('../renderer/src/assets/main.css', import.meta.url), 'utf8')
  assert.match(css, /\.settings-entry \{/)
  assert.match(css, /border-radius:\s*6px/)
  assert.equal(SETTINGS_SECTIONS.map((section) => section.id).join(','), 'recycle,general,appearance,models,addModel,skills,mcp,team')
})
