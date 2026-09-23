import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { mapCapabilityRow, parseCapabilitiesList } from './capability.model.ts'
import { CapabilityPanel } from './capabilityPanel.ts'

test('parseCapabilitiesList maps B11 rows and does not invent entries', () => {
  const rows = parseCapabilitiesList({
    capabilities: [
      {
        capability_id: 'skill:review',
        kind: 'skill',
        name: 'review',
        installed: true,
        enabled: true,
        authorized: true,
        available: true,
        connection: 'n/a',
        error: null,
        origin: '/skills/review'
      },
      {
        capability_id: 'mcp:git',
        kind: 'mcp',
        name: 'git',
        installed: true,
        enabled: false,
        authorized: true,
        available: false,
        connection: 'disconnected',
        error: 'mcp disconnected',
        origin: 'git'
      }
    ]
  })
  assert.equal(rows.length, 2)
  assert.equal(rows[0]?.capabilityId, 'skill:review')
  assert.equal(rows[0]?.kind, 'skill')
  assert.equal(rows[1]?.enabled, false)
  assert.equal(rows[1]?.error, 'mcp disconnected')
  assert.deepEqual(parseCapabilitiesList({}), [])
  assert.deepEqual(parseCapabilitiesList(null), [])
  assert.equal(mapCapabilityRow({ capability_id: 'skill:x', kind: 'skill', name: 'x' }).enabled, false)
})

test('CapabilityPanel lists protocol rows and exposes set_enabled toggle', () => {
  const html = renderToStaticMarkup(
    createElement(CapabilityPanel, {
      kind: 'skill',
      items: [
        {
          capabilityId: 'skill:review',
          kind: 'skill',
          name: 'review',
          installed: true,
          enabled: true,
          authorized: true,
          available: true,
          connection: 'n/a',
          error: null,
          origin: '/skills/review',
          description: '',
          scope: '',
          body: ''
        }
      ],
      onSetEnabled: () => undefined
    })
  )
  assert.match(html, /data-testid="capability-list-skill"/)
  assert.match(html, /data-testid="capability-row-skill:review"/)
  assert.match(html, /data-testid="capability-enabled-skill:review"/)
  assert.match(html, /review/)
  const empty = renderToStaticMarkup(
    createElement(CapabilityPanel, { kind: 'mcp', items: [], error: 'capabilities/list failed', onSetEnabled: () => undefined })
  )
  assert.match(empty, /data-testid="capability-list-mcp"/)
  assert.match(empty, /capabilities\/list failed/)
  assert.doesNotMatch(empty, /BLOCKED_PREREQUISITE/)
})
