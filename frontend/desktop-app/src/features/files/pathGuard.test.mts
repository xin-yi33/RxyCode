import assert from 'node:assert/strict'
import { test } from 'node:test'
import { interceptOutsidePath } from './pathGuard.ts'
import { classifyPreview, PREVIEW_READONLY } from '../preview/previewKinds.ts'
import { confirmDestructive, worktreesIsolated } from '../worktrees/worktreeIsolation.ts'

test('H10: workspace-outside paths are intercepted; preview is readonly', () => {
  assert.equal(interceptOutsidePath('D:\\repo', 'D:\\repo\\src\\a.ts'), null)
  assert.match(interceptOutsidePath('D:\\repo', 'C:\\Windows\\system32') ?? '', /outside/)
  assert.equal(PREVIEW_READONLY, true)
  assert.equal(classifyPreview('readme.md'), 'markdown')
  assert.equal(classifyPreview('shot.png'), 'image')
})

test('H10: two threads do not share worktree dirs; dirty delete confirms', () => {
  assert.equal(
    worktreesIsolated(
      { threadId: 't1', path: 'D:\\repo\\.wt\\a', dirty: false },
      { threadId: 't2', path: 'D:\\repo\\.wt\\b', dirty: true }
    ),
    true
  )
  assert.equal(confirmDestructive(true, 'prune'), 'confirm')
})
