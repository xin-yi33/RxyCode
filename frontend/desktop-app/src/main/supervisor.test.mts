import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { test } from 'node:test'
import type { AppserverStatus } from './appserver.ts'
import {
  getSharedSupervisor,
  lifecycleFromProtocolMessage,
  ProcessSupervisor,
  resetSharedSupervisor,
  type AppserverLike
} from './supervisor.ts'

class FakeManager extends EventEmitter implements AppserverLike {
  status: AppserverStatus = 'stopped'
  pid: number | null = 42
  starts = 0
  stops = 0
  kills = 0

  start(): boolean {
    this.starts += 1
    if (this.status === 'running') return false
    this.status = 'running'
    this.emit('status', this.status)
    return true
  }

  async stop(): Promise<void> {
    this.stops += 1
    this.status = 'stopped'
    this.pid = null
    this.emit('status', this.status)
    this.emit('exit', { code: 0, signal: null })
  }

  kill(): void {
    this.kills += 1
    this.status = 'stopped'
    this.pid = null
    this.emit('status', this.status)
  }
}

test('H3: process lifecycle events are projected, not invented', () => {
  const event = lifecycleFromProtocolMessage({
    jsonrpc: '2.0',
    method: 'event/recovery_required',
    params: { session_id: 's1', reason: 'incomplete' }
  })
  assert.equal(event?.method, 'event/recovery_required')
  assert.equal(event?.params.session_id, 's1')
  assert.equal(lifecycleFromProtocolMessage({ method: 'session/new' }), null)
})

test('H3: start failure and immediate crash are visible', () => {
  const manager = new FakeManager()
  const supervisor = new ProcessSupervisor(manager)
  manager.status = 'crashed'
  manager.start = () => {
    manager.starts += 1
    manager.emit('error', new Error('spawn failed'))
    return false
  }
  supervisor.start()
  assert.ok(supervisor.snapshot().startFailures >= 1)
  manager.emit('exit', { code: 1, signal: null })
  assert.equal(supervisor.snapshot().lastExit?.code, 1)
})

test('H3: force-closing the last window kills appserver', () => {
  const manager = new FakeManager()
  const supervisor = new ProcessSupervisor(manager)
  supervisor.start()
  supervisor.openWindow()
  supervisor.openWindow()
  supervisor.closeWindow()
  assert.equal(manager.kills, 0)
  assert.equal(supervisor.snapshot().windowCount, 1)
  supervisor.closeWindow()
  assert.equal(manager.kills, 1)
  assert.equal(supervisor.snapshot().windowCount, 0)
})

test('H3: restart recovers and recovery_required is sticky until process_started', () => {
  const manager = new FakeManager()
  const supervisor = new ProcessSupervisor(manager)
  supervisor.noteProtocolMessage({
    method: 'event/recovery_required',
    params: { session_id: 's1' }
  })
  assert.equal(supervisor.snapshot().recoveryRequired, true)
  return supervisor.restart().then((snap) => {
    assert.equal(manager.stops, 1)
    assert.equal(manager.starts, 1)
    assert.equal(snap.status, 'running')
    supervisor.noteProtocolMessage({
      method: 'event/process_started',
      params: { recovery_required: false }
    })
    assert.equal(supervisor.snapshot().recoveryRequired, false)
  })
})

test('H3: 20 start/stop cycles leave no live child', async () => {
  const manager = new FakeManager()
  const supervisor = new ProcessSupervisor(manager)
  for (let i = 0; i < 20; i += 1) {
    supervisor.start()
    await supervisor.stop()
  }
  assert.equal(manager.starts, 20)
  assert.equal(manager.stops, 20)
  assert.equal(supervisor.snapshot().status, 'stopped')
  assert.equal(supervisor.snapshot().pid, null)
})

test('H3: multi-window shares one supervisor', () => {
  resetSharedSupervisor()
  const first = getSharedSupervisor()
  const second = getSharedSupervisor()
  assert.equal(first, second)
  resetSharedSupervisor()
})
