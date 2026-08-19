import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  canShowAutoReview,
  oneAllowDoesNotGrantNext,
  scopeDoesNotSpread,
  submitDecision
} from './approvalView.ts'

test('H8: buttons only submit allow/deny/ask/cancel with approval_id', () => {
  const req = submitDecision('apr-1', 'allow')
  assert.equal(req.method, 'approval/respond')
  assert.equal(req.params.approval_id, 'apr-1')
  assert.equal(req.params.decision, 'allow')
})

test('H8: auto_review hidden unless capability; allow does not leak; scope stays', () => {
  assert.equal(canShowAutoReview({}), false)
  assert.equal(canShowAutoReview({ auto_review: true }), true)
  assert.equal(oneAllowDoesNotGrantNext('a', 'b'), true)
  assert.equal(scopeDoesNotSpread('D:\\p1', 'D:\\p2'), true)
})
