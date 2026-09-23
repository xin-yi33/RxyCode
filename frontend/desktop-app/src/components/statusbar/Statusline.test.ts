import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { Statusline, statuslineUsageSource } from './Statusline.ts'
import { contextWarn, visibleStatuslineItems } from './statusline.config.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX7: consume event/token_usage and event/agent_usage; cost PENDING_PRICING', () => {
  const source = statuslineUsageSource(schema)
  assert.equal(source.event, 'event/token_usage')
  assert.equal(source.agentUsage, true)
  assert.equal(source.pendingPricing, true)
  assert.deepEqual(
    visibleStatuslineItems(['model', 'context', 'tokens', 'cost'], { hasPricing: false, narrow: false }),
    ['model', 'context', 'tokens']
  )
  assert.equal(contextWarn(51, 100), true)
  assert.equal(contextWarn(10, 100), false)
})

test('GX7: statusline five states and no hardcoded 8192', () => {
  assert.equal(
    renderToStaticMarkup(createElement(Statusline, { hasSession: false })),
    ''
  )
  const html = renderToStaticMarkup(
    createElement(Statusline, { hasSession: true, model: 'grok', used: 10, limit: 100, tokens: 10 })
  )
  assert.match(html, /data-testid="statusline"/)
  assert.match(html, /data-source="event\/token_usage"/)
  assert.doesNotMatch(html, /8192/)
  const narrow = renderToStaticMarkup(
    createElement(Statusline, { hasSession: true, narrow: true, model: 'grok', used: 1, limit: 2 })
  )
  assert.match(narrow, /data-visual-state="narrow"/)
  assert.doesNotMatch(narrow, /data-item="tokens"/)
})
