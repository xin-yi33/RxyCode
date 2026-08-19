import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AppServerManager, type SpawnSpec } from './appserver.ts'

function delay(ms: number): Promise<void> {
  return new Promise((resolveWait) => setTimeout(resolveWait, ms))
}

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function pythonSpec(source: string): SpawnSpec {
  return {
    command: 'python',
    args: ['-c', source],
    cwd: process.cwd(),
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    detached: process.platform !== 'win32'
  }
}

test('H3: start failure when the executable is missing', async () => {
  const manager = new AppServerManager({
    guard: false,
    spawnOverride: {
      command: 'rxycode-missing-appserver-bin',
      args: [],
      cwd: process.cwd(),
      env: process.env,
      detached: false
    }
  })
  manager.start()
  await assert.rejects(manager.waitUntilRunning(3_000), /crashed|ENOENT|not found|timed out/i)
  assert.equal(manager.pid, null)
})

test('H3: appserver that exits immediately is crashed with an exit code', async () => {
  const manager = new AppServerManager({
    guard: false,
    spawnOverride: pythonSpec('import sys; sys.exit(1)')
  })
  manager.start()
  const exit = await new Promise<void>((resolve) => {
    manager.on('exit', () => resolve())
    manager.on('status', (status) => {
      if (status === 'crashed' || status === 'stopped') resolve()
    })
    setTimeout(resolve, 8_000)
  })
  void exit
  assert.ok(manager.status === 'crashed' || manager.lastExit?.code === 1)
})

test('H3: start wait is cancellable and times out without leaving a child', async () => {
  const manager = new AppServerManager({
    guard: false,
    spawnOverride: pythonSpec('import time; time.sleep(60)')
  })
  manager.start()
  const controller = new AbortController()
  const pending = manager.waitUntilRunning(15_000, controller.signal)
  controller.abort()
  await assert.rejects(pending, /cancelled/)
  await manager.stop()
  const pid = manager.pid
  if (pid !== null) {
    await delay(200)
    assert.equal(isAlive(pid), false)
  }
})

test('H3: 20 start/stop cycles leave no orphan process', async () => {
  const pids: number[] = []
  for (let i = 0; i < 20; i += 1) {
    const manager = new AppServerManager({
      guard: false,
      spawnOverride: pythonSpec('import sys; sys.stdin.read()')
    })
    manager.start()
    await manager.waitUntilRunning(10_000)
    const pid = manager.pid
    assert.ok(pid !== null)
    pids.push(pid as number)
    await manager.stop()
    await delay(50)
    assert.equal(isAlive(pid as number), false)
  }
  assert.equal(pids.length, 20)
})
