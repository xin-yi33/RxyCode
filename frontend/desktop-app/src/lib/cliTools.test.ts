import assert from 'node:assert/strict'
import { test } from 'node:test'
import { groupTools, PHASE_I_ATTACHMENT_PROTOCOL } from './cliTools.ts'
import { canRender, normalizePreviewPath } from '../features/preview/previewGallery.ts'
import { galleryVisualState } from '../features/preview/galleryVisualState.ts'

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

test('H19 five-state empty/loading/error/narrow/dark', () => {
  assert.equal(galleryVisualState({ artifacts: [], loading: true, error: null, narrow: false, dark: true }), 'loading')
  assert.equal(galleryVisualState({ artifacts: [], loading: false, error: 'x', narrow: false, dark: true }), 'error')
  assert.equal(galleryVisualState({ artifacts: [], loading: false, error: null, narrow: false, dark: true }), 'empty')
  assert.equal(
    galleryVisualState({
      artifacts: [{ kind: 'hero', path: 'a.png', bytes: 1 }],
      loading: false,
      error: null,
      narrow: true,
      dark: true
    }),
    'narrow'
  )
  assert.equal(
    galleryVisualState({
      artifacts: [{ kind: 'json', path: 'a.json', bytes: 1 }],
      loading: false,
      error: null,
      narrow: false,
      dark: true
    }),
    'dark'
  )
})
