import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isSuccess, projectExecItem, redactSecrets } from './toolCard.ts'

test('H7: keys and authorization are redacted; failed is not success', () => {
  const item = projectExecItem({
    id: '1',
    name: 'http',
    argsSummary: 'Authorization: Bearer sk-abc123secret',
    stdout: 'api_key=sk-abc',
    status: 'failed',
    exitCode: 1
  })
  assert.equal(item.argsSummary.includes('sk-abc'), false)
  assert.match(item.argsSummary, /REDACTED/)
  assert.equal(isSuccess(item), false)
  assert.equal(redactSecrets('token Authorization: Bearer xyz').includes('xyz'), false)
})

test('H7: running/ok/cancelled/timed_out/approval states are preserved', () => {
  for (const status of ['running', 'ok', 'cancelled', 'timed_out', 'approval'] as const) {
    assert.equal(projectExecItem({ id: status, name: 'bash', status }).status, status)
  }
})
