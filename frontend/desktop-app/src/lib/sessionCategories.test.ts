import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CHEVRON_GAP_PX, chevron, HOVER_DARK, HOVER_LIGHT, projectCategories } from './sessionCategories.ts'

test('H15: pin goes to pinned; project grouping; recycle BLOCKED without B17', () => {
  const buckets = projectCategories(
    [
      { sessionId: '1', title: 'a', workspaceRoot: 'D:\\a', pinned: true },
      { sessionId: '2', title: 'b', workspaceRoot: 'D:\\b', projectId: 'p' },
      { sessionId: '3', title: 'c', workspaceRoot: 'D:\\c' },
      { sessionId: '4', title: 'gone', workspaceRoot: 'D:\\d', deletedAt: 'now' }
    ],
    false
  )
  assert.equal(buckets.pinned[0]?.sessionId, '1')
  assert.equal(buckets.projects.p?.[0]?.sessionId, '2')
  assert.equal(buckets.recent[0]?.sessionId, '3')
  assert.equal(buckets.recycleBlocked, true)
  assert.equal(chevron(false), '>')
  assert.equal(chevron(true), 'v')
  assert.equal(CHEVRON_GAP_PX, 4)
  assert.equal(HOVER_LIGHT, 'rgba(0,0,0,0.06)')
  assert.equal(HOVER_DARK, 'rgba(255,255,255,0.08)')
})
