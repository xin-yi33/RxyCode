import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { AgentActivity, probeTeamEvents } from './AgentActivity.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX19: consume event/team; hide without multi_agent capability', () => {
  const probe = probeTeamEvents(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('event/team'))
  const hidden = renderToStaticMarkup(
    createElement(AgentActivity, { capabilities: {}, events: [{ method: 'agent_started', agentId: 'a' }] })
  )
  assert.match(hidden, /agent-activity-hidden/)
  const shown = renderToStaticMarkup(
    createElement(AgentActivity, {
      capabilities: { multi_agent: true },
      events: [{ method: 'agent_started', agentId: 'a' }]
    })
  )
  assert.match(shown, /a:agent_started/)
})
