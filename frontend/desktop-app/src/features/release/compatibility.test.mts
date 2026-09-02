import assert from 'node:assert/strict'
import { test } from 'node:test'
import { keepPreviousOnUpdateFailure, packageMismatch } from './compatibility.ts'
import { assertNoSecret } from '../../platform/secrets/secretGuard.ts'

test('H13: version mismatch is a clear error; failed update keeps old build', () => {
  assert.match(packageMismatch('1.3.0', '1.0.0', '1.1.0') ?? '', /mismatch/)
  assert.equal(keepPreviousOnUpdateFailure(false), 'keep')
  assert.equal(assertNoSecret({ crash: 'no key here' }), true)
})
