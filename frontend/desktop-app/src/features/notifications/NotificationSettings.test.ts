import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { classifyNotify, sanitizeNoticeBody, shouldNotify } from '../../main/notifier.ts'
import { NotificationSettings, probeNeedsInput } from './NotificationSettings.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX13: B12 probe consumes approval/request and event/agent_needs_input', () => {
  const probe = probeNeedsInput(schema)
  assert.ok(probe.consumed.includes('approval/request'))
  assert.ok(probe.present.includes('event/agent_needs_input'))
  assert.equal(classifyNotify('approval/request'), 'needs_input')
  assert.equal(classifyNotify('event/task_complete'), 'response')
  assert.equal(classifyNotify('event/message_delta'), null)
})

test('GX13: tiers, sanitize, settings UI', () => {
  assert.equal(shouldNotify('off', false, 'response'), false)
  assert.equal(shouldNotify('unfocused', true, 'response'), false)
  assert.equal(shouldNotify('unfocused', false, 'needs_input'), true)
  assert.match(sanitizeNoticeBody('token sk-abc123456789 plus more text that should clip'), /REDACTED/)
  assert.ok(sanitizeNoticeBody('x'.repeat(200)).length <= 80)
  const html = renderToStaticMarkup(
    createElement(NotificationSettings, { tier: 'unfocused', onChange: () => undefined })
  )
  assert.match(html, /unfocused/)
})
