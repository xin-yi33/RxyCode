import assert from 'node:assert/strict'
import { test } from 'node:test'
import { multiAgentUiVisible, reduceAgentEvents } from './agentEvents.ts'
import { teamMount } from '../features/team/gate.ts'

test('H18: no multi-agent UI without capability; no mock path', () => {
  assert.equal(multiAgentUiVisible({}), false)
  assert.deepEqual(
    reduceAgentEvents({}, [], { method: 'agent_started', agentId: 'a' }),
    []
  )
  assert.equal(teamMount({}), 'BLOCKED_PREREQUISITE')
  assert.equal(teamMount({ multi_agent: true }), 'ready')
})
