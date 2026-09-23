import assert from 'node:assert/strict'
import { test } from 'node:test'
import { displayMaxTokens, inferMaxTokensFromId } from './modelLimits.ts'
import { assertNoSecret, stripSecrets } from '../../platform/secrets/secretGuard.ts'
import { capabilityState } from '../capabilities/capabilityPanel.ts'
import { MCP_USES_TOOL_ITEMS } from '../mcp/mcpPanel.ts'

test('H11: max tokens come from resolver summary, never model id', () => {
  assert.equal(displayMaxTokens({ id: 'gpt', resolved_max_tokens: 8192, limit_source: 'phase3' }), '8192 (phase3)')
  assert.throws(() => inferMaxTokensFromId('gpt-4o'))
})

test('H11: secrets stay out of payload; undeclared capability is degraded', () => {
  assert.equal(assertNoSecret({ log: stripSecrets('key sk-abcdefghijk') }), true)
  assert.equal(capabilityState({}, 'mcp'), 'degraded')
  assert.equal(MCP_USES_TOOL_ITEMS, true)
})
