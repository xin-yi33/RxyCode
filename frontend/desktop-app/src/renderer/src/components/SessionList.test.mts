import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { CHEVRON_GAP_PX, chevron, HOVER_DARK, HOVER_LIGHT, projectCategories } from '../../../lib/sessionCategories.ts'
import { sessionVisualState } from './sessionVisualState.ts'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../assets/main.css'), 'utf8')

test('H15 five-state mapping covers empty/loading/error/narrow/dark', () => {
  assert.equal(sessionVisualState({ loading: true, error: null, empty: true, narrow: false, dark: true }), 'loading')
  assert.equal(sessionVisualState({ loading: false, error: 'x', empty: false, narrow: false, dark: true }), 'error')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: true, narrow: false, dark: true }), 'empty')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: true, dark: true }), 'narrow')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: false, dark: true }), 'dark')
  assert.equal(sessionVisualState({ loading: false, error: null, empty: false, narrow: false, dark: false }), 'ok')
})

test('H15 three categories, chevron, recycle BLOCKED, hover sample in CSS', () => {
  const buckets = projectCategories(
    [
      { sessionId: 'p', title: 'a', workspaceRoot: '', pinned: true },
      { sessionId: 'proj', title: 'b', workspaceRoot: 'D:\\work', projectId: 'D:\\work' },
      { sessionId: 'r', title: 'c', workspaceRoot: '' }
    ],
    false
  )
  assert.equal(buckets.pinned[0]?.sessionId, 'p')
  assert.equal(buckets.projects['D:\\work']?.[0]?.sessionId, 'proj')
  assert.equal(buckets.recent[0]?.sessionId, 'r')
  assert.equal(buckets.recycleBlocked, true)
  assert.equal(chevron(true), 'v')
  assert.equal(chevron(false), '>')
  assert.equal(CHEVRON_GAP_PX, 4)
  assert.equal(HOVER_LIGHT, 'rgba(0,0,0,0.06)')
  assert.equal(HOVER_DARK, 'rgba(255,255,255,0.08)')
  assert.match(css, /rgba\(255,\s*255,\s*255,\s*0\.08\)/)
  assert.match(css, /rgba\(0,\s*0,\s*0,\s*0\.06\)/)
  assert.match(css, /margin-left:\s*4px/)
  assert.match(css, /session-panel\[data-visual-state='narrow'\]/)
})
