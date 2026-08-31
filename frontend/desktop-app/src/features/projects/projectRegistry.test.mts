import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  addProject,
  inaccessibleProjectError,
  isolateProjectCwds,
  loadProjects,
  matchProjectCwd,
  projectDisplayName,
  PROJECTS_STORAGE_KEY,
  removeProject,
  saveProjects,
  sidebarProjects,
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

test('addProject uses folder name and does not duplicate cwd', () => {
  const first = addProject([], 'D:\\papers\\thesis')
  assert.equal(first[0]?.displayName, 'thesis')
  assert.equal(projectDisplayName('D:\\papers\\thesis\\'), 'thesis')
  const again = addProject(first, 'D:/papers/thesis/')
  assert.equal(again.length, 1)
  assert.equal(matchProjectCwd(again, 'D:\\papers\\thesis')?.id, first[0]?.id)
})

test('load/save projects persist in localStorage and never delete files', () => {
  const store = new Map<string, string>()
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    }
  }
  saveProjects([a, b], storage)
  assert.equal(store.has(PROJECTS_STORAGE_KEY), true)
  const loaded = loadProjects(storage)
  assert.deepEqual(loaded.map((item) => item.id), ['p1', 'p2'])
  assert.equal(removeProject(loaded, 'p1').deletedFiles, false)
})

test('sidebarProjects keeps registered folders even with no sessions', () => {
  const rows = sidebarProjects(
    [{ id: 'p1', displayName: '论文', cwd: 'D:\\papers', accessible: true }],
    { 'D:\\rxy': ['s1'] }
  )
  assert.deepEqual(rows.map((row) => row.displayName), ['论文', 'rxy'])
  assert.equal(rows[0]?.empty, true)
  assert.equal(rows[1]?.empty, false)
})
