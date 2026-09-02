import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CHEVRON_GAP_PX,
  chevron,
  HOVER_DARK,
  HOVER_LIGHT,
  PROJECT_SESSION_PREVIEW,
  projectCategories,
  projectNeedsExpand,
  visibleProjectSessions
} from './sessionCategories.ts'

test('H15: pin goes to pinned; project grouping; recycle BLOCKED without B17', () => {
  const buckets = projectCategories(
    [
      { sessionId: '1', title: 'a', workspaceRoot: 'D:\\a', pinned: true },
      { sessionId: '2', title: 'b', workspaceRoot: 'D:\\b', projectId: 'p' },
      { sessionId: '3', title: 'c', workspaceRoot: '' },
      { sessionId: '5', title: 'home', workspaceRoot: 'C:\\Users\\me\\.RxyCode' },
      { sessionId: '4', title: 'gone', workspaceRoot: 'D:\\d', deletedAt: 'now' }
    ],
    false
  )
  assert.equal(buckets.pinned[0]?.sessionId, '1')
  assert.equal(buckets.projects.p?.[0]?.sessionId, '2')
  assert.deepEqual(buckets.recent.map((row) => row.sessionId), ['3', '5'])
  assert.equal(buckets.recycleBlocked, true)
  assert.equal(chevron(false), '>')
  assert.equal(chevron(true), 'v')
  assert.equal(CHEVRON_GAP_PX, 4)
  assert.equal(HOVER_LIGHT, 'rgba(0,0,0,0.06)')
  assert.equal(HOVER_DARK, 'rgba(255,255,255,0.08)')
})

test('project folders collapse after five sessions until expanded', () => {
  const items = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
  assert.equal(PROJECT_SESSION_PREVIEW, 5)
  assert.equal(projectNeedsExpand(5), false)
  assert.equal(projectNeedsExpand(6), true)
  assert.deepEqual(visibleProjectSessions(items, false), ['a', 'b', 'c', 'd', 'e'])
  assert.deepEqual(visibleProjectSessions(items, true), items)
  assert.deepEqual(visibleProjectSessions(items.slice(0, 5), false), items.slice(0, 5))
})
