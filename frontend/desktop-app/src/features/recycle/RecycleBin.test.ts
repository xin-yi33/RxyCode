import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { PurgeConfirmDialog } from '../../components/PurgeConfirmDialog.ts'
import { TrashItem } from '../../components/TrashItem.ts'
import { TrashSection } from '../settings/TrashSection.ts'
import { RecycleBin } from './RecycleBin.ts'
import { B17_RECYCLE_METHODS, buildThreadPurge, probeRecycle } from './recycle.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

const item = {
  id: '1',
  title: 'old task',
  deletedAt: '2026-08-01T00:00:00.000Z',
  originCategory: 'recent' as const
}

test('GX21: B17 thread/list_deleted|restore|purge is path A, not session/*', () => {
  const probe = probeRecycle(schema)
  assert.equal(probe.path, 'A')
  for (const method of B17_RECYCLE_METHODS) {
    assert.ok(probe.present.includes(method), method)
  }
  assert.ok(!probe.present.includes('session/purge'))
  assert.deepEqual(buildThreadPurge(schema, false), { error: 'confirm_purge_required' })
  assert.deepEqual(buildThreadPurge(schema, true), {
    method: 'thread/purge',
    params: { confirm_purge: true }
  })
})

test('GX21: TrashItem shows name, deleted time, origin; PurgeConfirmDialog ships', () => {
  const row = renderToStaticMarkup(
    createElement(TrashItem, { item, onRestore: () => undefined })
  )
  assert.match(row, /old task/)
  assert.match(row, /data-testid="trash-deleted-at"/)
  assert.match(row, /2026-08-01T00:00:00.000Z/)
  assert.match(row, /data-origin="recent"/)
  const dialog = renderToStaticMarkup(
    createElement(PurgeConfirmDialog, {
      open: true,
      onCancel: () => undefined,
      onConfirm: () => undefined
    })
  )
  assert.match(dialog, /data-testid="purge-confirm-dialog"/)
  assert.match(dialog, /将永久删除会话记录与关联文件/)
  assert.match(dialog, /data-action="cancel"/)
  assert.match(dialog, /data-step="first"/)
})

test('GX21: TrashSection five states + BLOCKED missing list; RecycleBin mounts dialog', () => {
  const html = renderToStaticMarkup(
    createElement(TrashSection, {
      items: [item],
      blocked: true,
      missing: ['thread/list_deleted', 'thread/restore', 'thread/purge'],
      onRestore: () => undefined,
      onPurgeConfirmed: () => undefined
    })
  )
  assert.match(html, /data-testid="trash-section"/)
  assert.match(html, /BLOCKED_PREREQUISITE/)
  assert.match(html, /thread\/list_deleted/)
  assert.match(html, /data-action="restore"/)
  const empty = renderToStaticMarkup(
    createElement(RecycleBin, {
      items: [],
      blocked: true,
      missing: ['thread/purge'],
      onRestore: () => undefined,
      onPurgeConfirmed: () => undefined
    })
  )
  assert.match(empty, /data-visual-state="empty"/)
})
