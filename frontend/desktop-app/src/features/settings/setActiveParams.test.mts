import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSetActiveParams, requestSetActive } from './setActiveParams.ts'

test('H16: set_active omits effort when unset and sends optional_field when chosen', () => {
  assert.deepEqual(buildSetActiveParams('m1'), { id: 'm1' })
  assert.deepEqual(buildSetActiveParams('m1', ''), { id: 'm1' })
  assert.deepEqual(buildSetActiveParams('m1', null), { id: 'm1' })
  assert.deepEqual(buildSetActiveParams('m1', 'high'), { id: 'm1', effort: 'high' })
})

test('H16: requestSetActive drives models/set_active with effort on the real RPC helper', async () => {
  const calls: Array<{ method: string; params: unknown }> = []
  const ok = await requestSetActive(
    async (method, params) => {
      calls.push({ method, params })
      return { ok: true }
    },
    'gpt-x',
    'deep'
  )
  assert.equal(ok, true)
  assert.deepEqual(calls, [{ method: 'models/set_active', params: { id: 'gpt-x', effort: 'deep' } }])
})
