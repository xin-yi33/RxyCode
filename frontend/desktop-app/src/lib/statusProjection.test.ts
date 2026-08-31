import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fromSessionRunState, projectStatus, runningHighlight, sessionRowChrome, statusVisualState } from './statusProjection.ts'

test('H17: B5 states map to spin/dot/error without invented UI states', () => {
  assert.equal(projectStatus('running'), 'spin')
  assert.equal(projectStatus('completed'), 'dot')
  assert.equal(projectStatus('failed'), 'error')
  assert.equal(runningHighlight('running'), true)
  assert.equal(runningHighlight('completed'), false)
  assert.equal(fromSessionRunState('succeeded'), 'completed')
  assert.equal(fromSessionRunState('approval'), 'running')
})

test('idle new tasks hide chrome; only live runs spin; unread is a left dot', () => {
  assert.equal(sessionRowChrome({ runState: 'succeeded', running: false, unread: false }), 'idle')
  assert.equal(sessionRowChrome({ runState: 'queued', running: false, unread: false }), 'idle')
  assert.equal(sessionRowChrome({ runState: 'succeeded', running: true, unread: false }), 'spin')
  assert.equal(sessionRowChrome({ runState: 'running', running: false, unread: false }), 'spin')
  assert.equal(sessionRowChrome({ runState: 'approval', running: false, unread: false }), 'spin')
  assert.equal(sessionRowChrome({ runState: 'succeeded', running: false, unread: true }), 'unread')
  assert.equal(sessionRowChrome({ runState: 'succeeded', running: true, unread: true }), 'spin')
})

test('H17 five-state empty/loading/error/narrow/dark', () => {
  assert.equal(statusVisualState({ empty: true, loading: false, error: false, narrow: false, dark: true }), 'empty')
  assert.equal(statusVisualState({ empty: false, loading: true, error: false, narrow: false, dark: true }), 'loading')
  assert.equal(statusVisualState({ empty: false, loading: false, error: true, narrow: false, dark: true }), 'error')
  assert.equal(statusVisualState({ empty: false, loading: false, error: false, narrow: true, dark: true }), 'narrow')
  assert.equal(statusVisualState({ empty: false, loading: false, error: false, narrow: false, dark: true }), 'dark')
})
