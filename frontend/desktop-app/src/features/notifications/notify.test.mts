import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  dispatchRunEndNotice,
  electronOsNotify,
  noticeForRunEnd,
  watchRunStateTransitions
} from './notify.ts'

test('H17: stop/fail transitions from running are the only notify triggers', () => {
  const events = watchRunStateTransitions(
    { a: 'running', b: 'running', c: 'succeeded' },
    { a: 'cancelled', b: 'failed', c: 'running' }
  )
  assert.deepEqual(events, [
    { sessionId: 'a', state: 'cancelled' },
    { sessionId: 'b', state: 'failed' }
  ])
})

test('H17: mock Notification layer — OS path uses new Notification, Linux miss falls back to banner', () => {
  const constructed: Array<{ title: string; body: string }> = []
  const Original = globalThis.Notification
  class MockNotification {
    constructor(title: string, options?: { body?: string }) {
      constructed.push({ title, body: options?.body ?? '' })
    }
  }
  ;(globalThis as { Notification: typeof MockNotification }).Notification = MockNotification
  try {
    assert.equal(electronOsNotify('Task stopped', 's1'), true)
    assert.deepEqual(constructed, [{ title: 'Task stopped', body: 's1' }])
  } finally {
    if (Original === undefined) {
      Reflect.deleteProperty(globalThis, 'Notification')
    } else {
      globalThis.Notification = Original
    }
  }

  const banners: string[] = []
  assert.equal(
    dispatchRunEndNotice('s2', 'failed', {
      osNotify: () => {
        throw new Error('libnotify missing')
      },
      showBanner: (notice) => banners.push(notice.id)
    }),
    'banner'
  )
  assert.deepEqual(banners, ['fail:s2:failed'])
  assert.equal(noticeForRunEnd('s2', 'cancelled').kind, 'stop')
})
