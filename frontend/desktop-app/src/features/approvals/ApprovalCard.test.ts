import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { ApprovalCard } from './ApprovalCard.ts'
import { PermissionModeSwitcher } from './PermissionModeSwitcher.ts'
import {
  approvalChannel,
  buildModeSetRequest,
  gx2VisualState,
  mapPresetToB7,
  MODE_SET_CANDIDATE,
  probeModeSet,
  rejectFullWithoutEnable
} from './approval.mode.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX2: UI presets map onto B7 policies and never invent a third model', () => {
  assert.equal(mapPresetToB7('ask'), 'ask_for_each_risky_action')
  assert.equal(mapPresetToB7('auto'), 'allow_scoped_actions')
  assert.equal(mapPresetToB7('full'), 'full_access')
  assert.equal(rejectFullWithoutEnable('full', false), 'full_access_not_enabled')
  assert.equal(rejectFullWithoutEnable('full', true), null)
})

test('GX2: protocol probe — approval/mode_set is path A after backend merge', () => {
  const probe = probeModeSet(schema)
  assert.equal(probe.path, 'A')
  assert.deepEqual(probe.present, [MODE_SET_CANDIDATE])
  const request = buildModeSetRequest('ask', schema)
  assert.deepEqual(request, { method: MODE_SET_CANDIDATE, params: { preset: 'ask' } })
})

test('GX2: card vs modal mutex — high risk always modal', () => {
  assert.equal(approvalChannel({ risk: 'WRITE', preset: 'ask', action: 'edit file' }), 'card')
  assert.equal(approvalChannel({ risk: 'DANGER', preset: 'ask', action: 'rm -rf' }), 'modal')
  assert.equal(approvalChannel({ risk: 'WRITE', preset: 'ask', action: 'delete .env' }), 'modal')
})

test('GX2: ApprovalCard five states and allow/deny/cancel only', () => {
  assert.equal(gx2VisualState({ loading: true, error: null, empty: false, narrow: false, dark: false }), 'loading')
  assert.equal(gx2VisualState({ loading: false, error: 'e', empty: false, narrow: false, dark: false }), 'error')
  assert.equal(gx2VisualState({ loading: false, error: null, empty: true, narrow: false, dark: false }), 'empty')
  assert.equal(gx2VisualState({ loading: false, error: null, empty: false, narrow: true, dark: false }), 'narrow')
  assert.equal(gx2VisualState({ loading: false, error: null, empty: false, narrow: false, dark: true }), 'dark')

  const html = renderToStaticMarkup(
    createElement(ApprovalCard, {
      item: { requestId: 'r1', action: 'write src/a.ts', path: 'src/a.ts', risk: 'WRITE' },
      onAllow: () => undefined,
      onDeny: () => undefined,
      onCancel: () => undefined
    })
  )
  assert.match(html, /data-testid="approval-card"/)
  assert.match(html, /data-inline="true"/)
  assert.match(html, /data-action="allow"/)
  assert.match(html, /data-action="deny"/)
  assert.match(html, /data-action="cancel"/)
  assert.doesNotMatch(html, /mode_set/)

  const empty = renderToStaticMarkup(
    createElement(ApprovalCard, {
      item: null,
      onAllow: () => undefined,
      onDeny: () => undefined,
      onCancel: () => undefined
    })
  )
  assert.match(empty, /data-visual-state="empty"/)

  const switcher = renderToStaticMarkup(
    createElement(PermissionModeSwitcher, {
      preset: 'ask',
      fullEnabled: false,
      blocked: true,
      missingMethods: [MODE_SET_CANDIDATE],
      onRequestPreset: () => undefined
    })
  )
  assert.match(switcher, /BLOCKED_PREREQUISITE/)
  assert.match(switcher, /approval\/mode_set/)
})
