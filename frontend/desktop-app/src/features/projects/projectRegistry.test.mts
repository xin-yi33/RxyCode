import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  inaccessibleProjectError,
  isolateProjectCwds,
  removeProject,
  type ProjectRecord
} from './projectRegistry.ts'
import { bindThreadWorkspace, sessionNewParams } from '../workspaces/workspaceBinding.ts'

const a: ProjectRecord = {
  id: 'p1',
  displayName: 'Alpha',
  cwd: 'D:\\work\\alpha',
  accessible: true
}
const b: ProjectRecord = {
  id: 'p2',
  displayName: 'Beta',
  cwd: 'D:\\work\\beta',
  accessible: true
}

test('H4: two projects do not share cwd', () => {
  assert.equal(isolateProjectCwds([a, b]), true)
  assert.equal(isolateProjectCwds([a, { ...b, cwd: 'D:/work/alpha/' }]), false)
})

test('H4: new Thread must bind workspace_root', () => {
  const ok = bindThreadWorkspace('sess-1', 'D:\\work\\alpha')
  assert.ok('workspaceRoot' in ok)
  if ('workspaceRoot' in ok) {
    assert.equal(ok.workspaceRoot, 'D:\\work\\alpha')
  }
  const missing = bindThreadWorkspace('sess-1', '  ')
  assert.ok('error' in missing)
  assert.deepEqual(sessionNewParams('D:\\work\\alpha'), { workspace_root: 'D:\\work\\alpha' })
})

test('H4: removing a project never deletes user files', () => {
  const result = removeProject([a, b], 'p1')
  assert.equal(result.deletedFiles, false)
  assert.deepEqual(result.next.map((p) => p.id), ['p2'])
  assert.equal(a.cwd, 'D:\\work\\alpha')
})

test('H4: inaccessible directory has an understandable error', () => {
  const message = inaccessibleProjectError('Z:\\missing', 'ENOENT')
  assert.match(message, /not accessible/)
  assert.match(message, /Z:\\missing/)
})
