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
  applyTurnEndToPending,
  pushPending,
  removePending,
  reorderPending,
  shortcutIntent,
  takeNextPending
} from './pending.queue.ts'
import { buildSteer, probeSteer, steerRequestParams } from './steer.message.ts'

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

test('steerRequestParams includes every TurnSteerRequest required field from schema', () => {
  const required = (JSON.parse(schema) as {
    $defs: { TurnSteerRequest: { required: string[] } }
  }).$defs.TurnSteerRequest.required
  assert.ok(required.includes('session_id'))
  assert.ok(required.includes('text'))
  const params = steerRequestParams('sess-1', 'nudge the agent')
  assert.ok(params !== null)
  for (const field of required) {
    assert.equal(typeof params[field as keyof typeof params], 'string')
    assert.ok(String(params[field as keyof typeof params]).length > 0, `missing ${field}`)
  }
  assert.equal(params.session_id, 'sess-1')
  assert.equal(params.text, 'nudge the agent')
  assert.equal(steerRequestParams('', 'nudge'), null)
  assert.equal(steerRequestParams('sess-1', '   '), null)
})

test('buildSteer params satisfy schema and keep session_id', () => {
  const probe = probeSteer(schema)
  assert.equal(probe.path, 'A')
  assert.deepEqual(probe.missing, [])
  assert.equal(probe.stopMethod, 'session/interrupt')
  const steer = buildSteer(schema, 'nudge', 'sess-1')
  assert.equal(steer.method, 'turn/steer')
  if (!('params' in steer)) throw new Error('steer blocked')
  assert.equal(steer.params.session_id, 'sess-1')
  assert.equal(steer.params.text, 'nudge')
  const required = (JSON.parse(schema) as {
    $defs: { TurnSteerRequest: { required: string[] } }
  }).$defs.TurnSteerRequest.required
  for (const field of required) {
    assert.ok(Object.hasOwn(steer.params, field))
  }
})

test('queued messages flush FIFO when the turn ends', () => {
  let queue = pushPending([], { id: '1', text: 'first' })
  queue = pushPending(queue, { id: '2', text: 'second' })
  const taken = takeNextPending(queue)
  assert.equal(taken.item?.text, 'first')
  assert.deepEqual(taken.remaining.map((item) => item.text), ['second'])
  const flushed = applyTurnEndToPending(
    { s1: taken.remaining, s2: [{ id: 'x', text: 'other' }] },
    { s1: true, s2: true },
    { s1: false, s2: true }
  )
  assert.deepEqual(flushed.toSend, [{ sessionId: 's1', text: 'second' }])
  assert.deepEqual(flushed.pendingBySession.s1, [])
  assert.equal(flushed.pendingBySession.s2?.[0]?.text, 'other')
  const idle = applyTurnEndToPending({ s1: [{ id: '1', text: 'hold' }] }, { s1: true }, { s1: true })
  assert.deepEqual(idle.toSend, [])
  assert.equal(idle.pendingBySession.s1?.[0]?.text, 'hold')
})

test('App uses the steer builder and drains the queue; no second permission switcher', () => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/App.tsx'), 'utf8')
  const composer = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../renderer/src/components/Composer.tsx'),
    'utf8'
  )
  assert.doesNotMatch(app, /PermissionModeSwitcher/)
  assert.doesNotMatch(app, /gxPermissionPreset/)
  assert.match(app, /steerRequestParams/)
  assert.match(app, /applyTurnEndToPending/)
  assert.match(composer, /SendDropdown/)
  assert.match(composer, /data-testid=\{running \? 'composer-stop' : 'composer-send'\}/)
  assert.match(composer, /PermissionMenu/)
  assert.match(composer, /testId="composer-permission-mode"/)
  assert.doesNotMatch(app, /request\('turn\/steer',\s*\{\s*text\s*\}/)
})
