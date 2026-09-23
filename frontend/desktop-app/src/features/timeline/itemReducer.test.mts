import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  applyTimelineEvent,
  emptyTimeline,
  interruptPreserve,
  shouldRenderReasoning,
  virtualWindow
} from './itemReducer.ts'

test('H6: duplicate event_id does not duplicate text', () => {
  let state = emptyTimeline()
  state = applyTimelineEvent(state, { eventId: 'e1', sequence: 1, kind: 'message', text: 'hi' })
  state = applyTimelineEvent(state, { eventId: 'e1', sequence: 1, kind: 'message', text: 'hi' })
  assert.equal(state.items.length, 1)
})

test('H6: out-of-order deltas insert without dropping earlier text', () => {
  let state = emptyTimeline()
  state = applyTimelineEvent(state, { eventId: 'e2', sequence: 2, kind: 'tool', text: 'b', toolOk: true })
  state = applyTimelineEvent(state, { eventId: 'e1', sequence: 1, kind: 'message', text: 'a' })
  assert.deepEqual(
    state.items.map((item) => item.sequence),
    [1, 2]
  )
})

test('H6: interrupt keeps received content; failed tool is not success; no raw reasoning', () => {
  let state = applyTimelineEvent(emptyTimeline(), {
    eventId: 't1',
    sequence: 1,
    kind: 'tool',
    text: 'boom',
    toolOk: false
  })
  state = interruptPreserve(state)
  assert.equal(state.interrupted, true)
  assert.equal(state.items[0]?.toolOk, false)
  assert.equal(shouldRenderReasoning('secret chain'), false)
})

test('H6: 1000 items can be windowed', () => {
  let state = emptyTimeline()
  for (let i = 1; i <= 1000; i += 1) {
    state = applyTimelineEvent(state, { eventId: `e${i}`, sequence: i, kind: 'message', text: String(i) })
  }
  assert.equal(state.items.length, 1000)
  assert.equal(virtualWindow(state.items, 990, 20).length, 10)
})
