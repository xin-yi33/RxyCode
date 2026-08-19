import assert from 'node:assert/strict'
import { test } from 'node:test'
import { checkpointRestore, mustNotForgeReview, startReviewRequest } from './reviewProjection.ts'
import { emptyDiffState, foldLongLine } from '../git/diffView.ts'

test('H9: UI sends review/start and never forges a completed Review', () => {
  assert.equal(startReviewRequest('s1').method, 'review/start')
  assert.equal(mustNotForgeReview(true, null), false)
  assert.equal(
    mustNotForgeReview(true, { reviewId: 'r', findings: [], status: 'completed' }),
    true
  )
  assert.equal(checkpointRestore('cp1').method, 'checkpoint/restore')
})

test('H9: long diff lines fold; empty state is explicit', () => {
  assert.ok(foldLongLine('x'.repeat(500), 40).endsWith('…'))
  assert.equal(emptyDiffState(), 'empty')
})
