import assert from 'node:assert/strict'
import { test } from 'node:test'
import { groupTools, PHASE_I_ATTACHMENT_PROTOCOL } from './cliTools.ts'
import { canRender, normalizePreviewPath } from '../features/preview/previewGallery.ts'

test('H19: without B14 only builtin group; zero PHASE-I; four artifact kinds', () => {
  const groups = groupTools(
    [
      { id: 'bash', source: 'builtin' },
      { id: 'cli:foo', source: 'cli-hub' }
    ],
    false
  )
  assert.equal(groups.builtin.length, 2)
  assert.equal(groups['cli-hub'].length, 0)
  assert.equal(PHASE_I_ATTACHMENT_PROTOCOL, false)
  assert.equal(canRender({ kind: 'hero', path: 'a.png', bytes: 10 }), true)
  assert.equal(canRender({ kind: 'video', path: 'a.mp4', bytes: 10, durationSec: 9 }), false)
  assert.equal(normalizePreviewPath('D:\\x\\y'), 'D:/x/y')
})
