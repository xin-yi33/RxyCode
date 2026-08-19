import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { ModeSelector } from './ModeSelector.ts'
import { attachCapability, MODE_TO_CAPABILITY, planOverridesWrite, probeCapabilityField } from './mode.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX14: capability field missing on agent/invoke and session/prompt', () => {
  assert.equal(MODE_TO_CAPABILITY.ask, 'no_tools')
  assert.equal(MODE_TO_CAPABILITY.edit, 'edit_only')
  assert.equal(MODE_TO_CAPABILITY.agent, 'full')
  const probe = probeCapabilityField(schema)
  assert.equal(probe.presentOnInvoke, false)
  assert.equal(probe.presentOnPrompt, false)
  const attached = attachCapability(schema, 'edit', 'session/prompt')
  assert.equal('status' in attached && attached.status === 'BLOCKED_PREREQUISITE', true)
  assert.equal(planOverridesWrite(true, 'full'), 'plan')
})

test('GX14: selector UI', () => {
  const html = renderToStaticMarkup(
    createElement(ModeSelector, { mode: 'agent', blocked: true, onChange: () => undefined })
  )
  assert.match(html, /data-testid="mode-selector"/)
  assert.match(html, /data-capability="full"/)
})
