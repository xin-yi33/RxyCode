import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { ForkConversation } from './ForkConversation.ts'
import { SessionMenu } from './SessionMenu.ts'
import { buildIndex, searchIndex } from './session.search.ts'
import { buildFork, canForkFrom, probeSessionOps } from './session.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX8: rename exists; fork/pin/archive missing; only user messages fork', () => {
  const probe = probeSessionOps(schema)
  assert.ok(probe.present.includes('session/rename'))
  assert.equal(probe.forkPath, 'B')
  assert.ok(probe.missing.includes('thread/fork'))
  assert.equal(canForkFrom('user'), true)
  assert.equal(canForkFrom('assistant'), false)
  const req = buildFork(schema, { threadId: 't', messageId: 'm' })
  assert.equal('status' in req && req.status === 'BLOCKED_PREREQUISITE', true)
})

test('GX8: local search redacts secrets and drops deleted threads', () => {
  const index = buildIndex([
    { threadId: '1', title: 'fix login', text: 'use sk-secret123' },
    { threadId: '2', title: 'gone', text: 'x', deleted: true }
  ])
  assert.equal(index.length, 1)
  assert.match(index[0]?.text ?? '', /REDACTED/)
  assert.equal(searchIndex(index, 'login')[0]?.threadId, '1')
})

test('GX8: menu and fork UI', () => {
  const menu = renderToStaticMarkup(
    createElement(SessionMenu, {
      onRename: () => undefined,
      onPin: () => undefined,
      onArchive: () => undefined,
      onSearch: () => undefined,
      pinBlocked: true,
      archiveBlocked: true
    })
  )
  assert.match(menu, /Rename/)
  assert.match(menu, /thread\/pin/)
  const fork = renderToStaticMarkup(
    createElement(ForkConversation, { role: 'user', blocked: true, onFork: () => undefined })
  )
  assert.match(fork, /thread\/fork/)
})
