import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  archiveThread,
  bumpCursor,
  childDoesNotLeakIntoParent,
  confirmDelete,
  createThread,
  draftExcludedFromItems,
  filterThreads,
  forkThread,
  isDraftNotInput,
  mergeChildTree,
  parentChildNav,
  renameThread,
  restoreCursor,
  type ChildNode,
  type ThreadRecord
} from './threadProjection.ts'

const parent: ThreadRecord = {
  sessionId: 'p1',
  title: 'Parent',
  workspaceRoot: 'D:\\a',
  projectId: 'proj',
  status: 'active',
  cursor: 7
}
const child: ChildNode = {
  sessionId: 'c1',
  parentSessionId: 'p1',
  agentId: 'explore',
  trigger: 'mention',
  status: 'running',
  budget: { used: 1, limit: 10 },
  permission: 'read'
}

test('H5: filter by project/workspace/status', () => {
  const archived: ThreadRecord = { ...parent, sessionId: 'p2', status: 'archived' }
  assert.equal(filterThreads([parent, archived], { status: 'active' }).length, 1)
  assert.equal(filterThreads([parent], { projectId: 'proj', workspaceRoot: 'D:\\a' }).length, 1)
})

test('H5: cursor survives restore', () => {
  assert.equal(restoreCursor([parent], 'p1'), 7)
})

test('H5: child events are idempotent by event_id and stay off parent items', () => {
  const first = mergeChildTree([], child, 'evt-1', {})
  const dup = mergeChildTree(first.nodes, { ...child, status: 'failed' }, 'evt-1', first.seen)
  assert.equal(dup.nodes[0]?.status, 'running')
  assert.equal(childDoesNotLeakIntoParent([{ sessionId: 'p1' }], child), true)
})

test('H5: draft is not treated as submitted input; delete needs confirm', () => {
  assert.equal(isDraftNotInput({ sessionId: 'p1', text: 'wip' }), true)
  assert.equal(confirmDelete(parent, false, 't1').status, 'pending')
  const gone = confirmDelete(parent, true, '2026-08-19T00:00:00Z')
  assert.equal(gone.status, 'soft-delete')
  assert.equal(gone.thread.status, 'trashed')
})

test('H5: create rename archive fork restore and parent nav', () => {
  const created = createThread('sess-new', 'D:\\a', 'New')
  const renamed = renameThread(created, 'Renamed')
  const archived = archiveThread(renamed)
  const forked = forkThread(archived, 'p1-fork')
  assert.equal(renamed.title, 'Renamed')
  assert.equal(archived.status, 'archived')
  assert.equal(forked.parentSessionId, created.sessionId)
  assert.equal(forked.status, 'active')
  assert.equal(parentChildNav([parent], child).parent?.sessionId, 'p1')
  assert.equal(bumpCursor(parent, 3).cursor, 7)
  assert.equal(bumpCursor(parent, 9).cursor, 9)
  assert.equal(draftExcludedFromItems({ sessionId: 'p1', text: 'wip' }, [{ text: 'hello' }]), true)
})
