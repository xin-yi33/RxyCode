import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { QueuedFollowups } from './QueuedFollowups.ts'
import { queueOnEnter, takePendingById } from './queuedFollowup.ts'

test('running Enter queues only when queue mode is on', () => {
  assert.equal(queueOnEnter(true, 'on'), true)
  assert.equal(queueOnEnter(true, 'off'), false)
  assert.equal(queueOnEnter(false, 'on'), false)
})

test('takePendingById pulls one follow-up for send now', () => {
  const taken = takePendingById(
    [
      { id: 'a', text: 'first' },
      { id: 'b', text: 'second' }
    ],
    'b'
  )
  assert.equal(taken.item?.text, 'second')
  assert.deepEqual(taken.remaining.map((row) => row.id), ['a'])
})

test('queued follow-ups render send now, delete, and the Codex more menu', () => {
  const html = renderToStaticMarkup(
    createElement(QueuedFollowups, {
      items: [{ id: '1', text: '你好啊，你是谁？有什么作用呢？' }],
      onSendNow: () => undefined,
      onDelete: () => undefined,
      onEdit: () => undefined,
      onOpenSideChat: () => undefined,
      onTurnOff: () => undefined
    })
  )
  assert.match(html, /data-testid="queued-followups"/)
  assert.match(html, /调整方向/)
  assert.match(html, /data-testid="queue-delete-1"/)
  assert.match(html, /data-testid="queue-more-1"/)
  assert.doesNotMatch(html, /Add to Queue/)
  assert.doesNotMatch(html, /Steer with Message/)
})
