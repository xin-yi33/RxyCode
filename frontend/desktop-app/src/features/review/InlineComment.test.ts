import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { InlineComment } from './InlineComment.ts'
import { ReviewScopeSelector } from './ReviewScopeSelector.ts'
import {
  buildCommentAdd,
  canReopen,
  draftFromComments,
  gx3VisualState,
  markStale,
  probeReviewComments,
  resolveComment,
  REVIEW_SCOPES,
  type InlineCommentRecord
} from './review.comments.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX3: five review scopes frozen including last_turn', () => {
  assert.deepEqual(REVIEW_SCOPES, ['unstaged', 'staged', 'commit', 'branch', 'last_turn'])
  const html = renderToStaticMarkup(
    createElement(ReviewScopeSelector, { value: 'last_turn', onChange: () => undefined })
  )
  assert.match(html, /last_turn/)
})

test('GX3: comment state machine open→stale→resolved and no reopen from stale', () => {
  const open: InlineCommentRecord = {
    id: 'c1',
    file: 'a.ts',
    line: 3,
    hunkHash: 'h1',
    body: 'nits',
    status: 'open'
  }
  const stale = markStale(open, 'h2')
  assert.equal(stale.status, 'stale')
  assert.equal(resolveComment(stale).status, 'resolved')
  assert.equal(canReopen(stale), false)
})

test('GX3: comment protocol is path A; draft stays local until add RPC', () => {
  const probe = probeReviewComments(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('review/comment/add'))
  assert.ok(probe.present.includes('review/comment/resolve'))
  const payload = {
    reviewId: 'r',
    file: 'a.ts',
    line: 1,
    hunkHash: 'h',
    body: 'x'
  }
  const req = buildCommentAdd(schema, payload)
  assert.deepEqual(req, { method: 'review/comment/add', params: payload })
  assert.match(draftFromComments([{ id: '1', file: 'a.ts', line: 1, hunkHash: 'h', body: 'fix', status: 'open' }]), /请处理以下内联评论/)
})

test('GX3: InlineComment five states', () => {
  assert.equal(gx3VisualState({ loading: true, error: null, empty: false, narrow: false, dark: false }), 'loading')
  const html = renderToStaticMarkup(
    createElement(InlineComment, {
      file: 'a.ts',
      line: 4,
      hunkHash: 'h',
      comments: [],
      blockedReason: 'BLOCKED_PREREQUISITE: review/comment/add',
      onAdd: () => undefined,
      onResolve: () => undefined
    })
  )
  assert.match(html, /data-testid="inline-comment"/)
  assert.match(html, /BLOCKED_PREREQUISITE/)
})
