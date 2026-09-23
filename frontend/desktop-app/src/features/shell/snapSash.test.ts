import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  applySnapDrag,
  bandOf,
  LEFT_SNAP,
  RIGHT_SNAP,
  WORKBENCH_PANES_KEY,
  loadWorkbenchPanes,
  saveWorkbenchPanes
} from './snapSash.ts'

test('shrinking from preferred snaps fully collapsed without a dwell', () => {
  const result = applySnapDrag(LEFT_SNAP, {
    origin: 'preferred',
    proposed: 180,
    now: 1_000,
    dwellStartedAt: null
  })
  assert.deepEqual(result, { size: 0, band: 'collapsed', dwellStartedAt: null, snap: true })
})

test('growing from preferred is free and can stop at any size up to max', () => {
  const mid = applySnapDrag(LEFT_SNAP, {
    origin: 'preferred',
    proposed: 360,
    now: 1_000,
    dwellStartedAt: null
  })
  assert.equal(mid.band, 'free')
  assert.equal(mid.size, 360)
  assert.equal(mid.snap, false)
  const capped = applySnapDrag(LEFT_SNAP, {
    origin: 'preferred',
    proposed: 900,
    now: 1_000,
    dwellStartedAt: null
  })
  assert.equal(capped.size, LEFT_SNAP.max)
})

test('shrinking from max dwells at preferred then collapses', () => {
  const hit = applySnapDrag(LEFT_SNAP, {
    origin: 'free',
    proposed: 200,
    now: 5_000,
    dwellStartedAt: null
  })
  assert.equal(hit.size, LEFT_SNAP.preferred)
  assert.equal(hit.band, 'preferred')
  assert.equal(hit.snap, true)
  assert.equal(hit.dwellStartedAt, 5_000)

  const holding = applySnapDrag(LEFT_SNAP, {
    origin: 'free',
    proposed: 120,
    now: 5_100,
    dwellStartedAt: 5_000
  })
  assert.equal(holding.size, LEFT_SNAP.preferred)
  assert.equal(holding.band, 'preferred')

  const gone = applySnapDrag(LEFT_SNAP, {
    origin: 'free',
    proposed: 80,
    now: 5_300,
    dwellStartedAt: 5_000
  })
  assert.deepEqual(gone, { size: 0, band: 'collapsed', dwellStartedAt: null, snap: true })
})

test('expanding from collapsed snaps to preferred instead of stopping halfway', () => {
  const still = applySnapDrag(LEFT_SNAP, {
    origin: 'collapsed',
    proposed: 40,
    now: 1,
    dwellStartedAt: null
  })
  assert.equal(still.band, 'collapsed')
  const opened = applySnapDrag(LEFT_SNAP, {
    origin: 'collapsed',
    proposed: 80,
    now: 1,
    dwellStartedAt: null
  })
  assert.equal(opened.size, LEFT_SNAP.preferred)
  assert.equal(opened.snap, true)
})

test('a short pull opens a wide right panel to preferred', () => {
  const opened = applySnapDrag(RIGHT_SNAP, {
    origin: 'collapsed',
    proposed: 80,
    now: 1,
    dwellStartedAt: null
  })
  assert.equal(opened.size, RIGHT_SNAP.preferred)
  assert.equal(opened.snap, true)
})

test('bandOf maps stored sizes', () => {
  assert.equal(bandOf(0, LEFT_SNAP), 'collapsed')
  assert.equal(bandOf(248, LEFT_SNAP), 'preferred')
  assert.equal(bandOf(400, LEFT_SNAP), 'free')
})

test('workbench pane sizes persist without throwing on junk', () => {
  const memory = new Map<string, string>()
  const storage = {
    getItem: (key: string): string | null => memory.get(key) ?? null,
    setItem: (key: string, value: string): void => {
      memory.set(key, value)
    }
  }
  saveWorkbenchPanes({ left: 300, right: 400, bottom: 220 }, storage)
  assert.equal(memory.get(WORKBENCH_PANES_KEY)?.includes('"left":300'), true)
  assert.deepEqual(loadWorkbenchPanes(storage), { left: 300, right: 400, bottom: 220 })
  memory.set(WORKBENCH_PANES_KEY, '{')
  assert.equal(loadWorkbenchPanes(storage).left, 248)
})
