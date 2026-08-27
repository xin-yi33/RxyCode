import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { CheckpointTimeline } from './CheckpointTimeline.ts'
import { MessageRevertButton } from './MessageRevertButton.ts'
import { buildRewind, gx4VisualState, probeCheckpoints } from './checkpoint.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX4: checkpoint rewind/snapshot is path A; confirm still required', () => {
  const probe = probeCheckpoints(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('checkpoint/rewind'))
  assert.deepEqual(buildRewind(schema, 'c1', false), { error: 'confirm_required' })
  assert.deepEqual(buildRewind(schema, 'c1', true), {
    method: 'checkpoint/rewind',
    params: { checkpoint_id: 'c1', confirm: true }
  })
})

test('GX4: timeline five states and revert hover entry', () => {
  assert.equal(gx4VisualState({ loading: false, error: null, empty: true, narrow: false, dark: false }), 'empty')
  const html = renderToStaticMarkup(
    createElement(CheckpointTimeline, {
      points: [{ checkpointId: 'c1', seq: 1, name: 'before-refactor', createdAt: 't' }],
      onSelect: () => undefined
    })
  )
  assert.match(html, /before-refactor/)
  const revert = renderToStaticMarkup(
    createElement(MessageRevertButton, {
      checkpointId: 'c1',
      fileCount: 3,
      messageCount: 2,
      blocked: true,
      missing: ['checkpoint/rewind'],
      onConfirm: () => undefined
    })
  )
  assert.match(revert, /BLOCKED_PREREQUISITE/)
})
