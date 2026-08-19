import assert from 'node:assert/strict'
import { test } from 'node:test'
import { projectStatus, runningHighlight } from './statusProjection.ts'

test('H17: B5 states map to spin/dot/error without invented UI states', () => {
  assert.equal(projectStatus('running'), 'spin')
  assert.equal(projectStatus('completed'), 'dot')
  assert.equal(projectStatus('failed'), 'error')
  assert.equal(runningHighlight('running'), true)
  assert.equal(runningHighlight('completed'), false)
})
