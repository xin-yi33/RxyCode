import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { SideChatPanel } from './SideChatPanel.ts'
import { buildSideChatCreate, probeSideChat } from './sideChat.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX16: side chat methods are path A', () => {
  const probe = probeSideChat(schema)
  assert.equal(probe.path, 'A')
  const req = buildSideChatCreate(schema, 't1')
  assert.deepEqual(req, { method: 'thread/side_chat/create', params: { thread_id: 't1' } })
  const html = renderToStaticMarkup(
    createElement(SideChatPanel, { blocked: false, missing: [] })
  )
  assert.match(html, /data-testid="side-chat"/)
})
