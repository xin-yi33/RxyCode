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

test('GX16: side chat methods missing', () => {
  const probe = probeSideChat(schema)
  assert.equal(probe.path, 'B')
  const req = buildSideChatCreate(schema, 't1')
  assert.equal('status' in req && req.status === 'BLOCKED_PREREQUISITE', true)
  const html = renderToStaticMarkup(
    createElement(SideChatPanel, { blocked: true, missing: probe.missing })
  )
  assert.match(html, /thread\/side_chat\/create/)
})
