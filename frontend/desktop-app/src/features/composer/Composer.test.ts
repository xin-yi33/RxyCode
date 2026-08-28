import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { SendDropdown } from './SendDropdown.ts'
import {
  PENDING_LIMIT,
  pushPending,
  removePending,
  reorderPending,
  shortcutIntent
} from './pending.queue.ts'
import { buildSteer, probeSteer } from './steer.message.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX5: pending queue push/reorder/delete/limit 10', () => {
  let queue = pushPending([], { id: '1', text: 'a' })
  queue = pushPending(queue, { id: '2', text: 'b' })
  queue = reorderPending(queue, 0, 1)
  assert.deepEqual(queue.map((i) => i.id), ['2', '1'])
  queue = removePending(queue, '2')
  assert.equal(queue.length, 1)
  for (let i = 0; i < 12; i += 1) queue = pushPending(queue, { id: `n${i}`, text: 'x' })
  assert.equal(queue.length, PENDING_LIMIT)
})

test('GX5: shortcuts and idle vs running dropdown', () => {
  assert.equal(shortcutIntent({ altKey: true, ctrlKey: false, metaKey: false, key: 'Enter' }), 'queue')
  assert.equal(shortcutIntent({ altKey: false, ctrlKey: true, metaKey: false, key: 'Enter' }), 'stop_and_send')
  const idle = renderToStaticMarkup(
    createElement(SendDropdown, { running: false, pendingCount: 0, onSend: () => undefined })
  )
  assert.match(idle, /data-testid="send-idle"/)
  const running = renderToStaticMarkup(
    createElement(SendDropdown, {
      running: true,
      pendingCount: 2,
      steerBlocked: true,
      onSend: () => undefined
    })
  )
  assert.match(running, /data-testid="send-dropdown"/)
  assert.match(running, /Add to Queue/)
  assert.match(running, /turn\/steer/)
})

test('Composer ships SendDropdown while running and keeps harness send/stop testids', () => {
  const composer = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/components/Composer.tsx'),
    'utf8'
  )
  assert.match(composer, /SendDropdown/)
  assert.match(composer, /data-testid=\{running \? 'composer-stop' : 'composer-send'\}/)
  assert.match(composer, /data-testid="composer-permission-mode"/)
})

test('App unmounts duplicate PermissionModeSwitcher', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/App.tsx'), 'utf8')
  assert.doesNotMatch(app, /PermissionModeSwitcher/)
  assert.doesNotMatch(app, /gxPermissionPreset/)
})

test('GX5: turn/steer is path A; session/interrupt present for stop', () => {
  const probe = probeSteer(schema)
  assert.equal(probe.path, 'A')
  assert.deepEqual(probe.missing, [])
  assert.equal(probe.stopMethod, 'session/interrupt')
  const steer = buildSteer(schema, 'nudge')
  assert.deepEqual(steer, { method: 'turn/steer', params: { text: 'nudge' } })
})
