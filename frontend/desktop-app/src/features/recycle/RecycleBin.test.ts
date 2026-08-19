import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { RecycleBin, probeRecycle } from './RecycleBin.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX21: consume session/trash restore purge', () => {
  const probe = probeRecycle(schema)
  assert.equal(probe.path, 'A')
  const html = renderToStaticMarkup(
    createElement(RecycleBin, {
      items: [{ id: '1', title: 'old' }],
      onRestore: () => undefined,
      onPurge: () => undefined
    })
  )
  assert.match(html, /Restore/)
  assert.match(html, /Purge/)
})
