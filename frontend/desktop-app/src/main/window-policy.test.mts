import assert from 'node:assert/strict'
import { test } from 'node:test'
import { WINDOW_POLICY, shouldQuitSecondInstance } from './window-policy.ts'

test('H3: Desktop is single-instance; a second process must quit', () => {
  assert.equal(WINDOW_POLICY, 'single-instance')
  assert.equal(shouldQuitSecondInstance(false), true)
  assert.equal(shouldQuitSecondInstance(true), false)
})
