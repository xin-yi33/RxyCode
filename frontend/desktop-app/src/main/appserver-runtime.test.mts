import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { AppServerManager, buildSpawnSpec } from './appserver.ts'
import type { BundledRuntime } from './runtime.ts'

function fixtureDir(): string {
  return mkdtempSync(join(tmpdir(), 'rxycode-appserver-runtime-test-'))
}

function fakeRuntime(base: string): BundledRuntime {
  const rootDir = join(base, 'runtime')
  mkdirSync(join(rootDir, 'python'), { recursive: true })
  mkdirSync(join(rootDir, 'app', 'appserver'), { recursive: true })
  writeFileSync(
    join(rootDir, 'manifest.json'),
    JSON.stringify({
      platform: 'win32',
      arch: 'x64',
      pythonVersion: '3.14.2',
      rxycodeVersion: '1.2.6',
      createdAt: '2026-08-08T00:00:00.000Z'
    })
  )
  writeFileSync(join(rootDir, 'python', 'python.exe'), 'fake')
  writeFileSync(join(rootDir, 'app', 'appserver', '__main__.py'), '')
  return {
    manifest: {
      platform: 'win32',
      arch: 'x64',
      pythonVersion: '3.14.2',
      rxycodeVersion: '1.2.6',
      createdAt: '2026-08-08T00:00:00.000Z'
    },
    rootDir,
    python: join(rootDir, 'python', 'python.exe'),
    appDir: join(rootDir, 'app')
  }
}

test('buildSpawnSpec prefers the bundled runtime python and app dir', () => {
  const base = fixtureDir()
  try {
    const runtime = fakeRuntime(base)
    const spec = buildSpawnSpec({ runtime, repoRoot: 'D:\\dev\\RxyCode-master' })
    assert.equal(spec.command, runtime.python)
    assert.deepEqual(spec.args, ['-m', 'appserver'])
    assert.equal(spec.cwd, runtime.appDir)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test('buildSpawnSpec falls back to python on PATH with the repo root cwd', () => {
  const spec = buildSpawnSpec({ runtime: null, repoRoot: 'D:\\dev\\RxyCode-master' })
  assert.equal(spec.command, 'python')
  assert.deepEqual(spec.args, ['-m', 'appserver'])
  assert.equal(spec.cwd, 'D:\\dev\\RxyCode-master')
})

test('buildSpawnSpec honors an explicit python override in dev mode', () => {
  const spec = buildSpawnSpec({
    python: 'C:\\Python312\\python.exe',
    runtime: null,
    repoRoot: 'D:\\dev\\RxyCode-master'
  })
  assert.equal(spec.command, 'C:\\Python312\\python.exe')
})

test('buildSpawnSpec uses the fake appserver script for fake mode', () => {
  const spec = buildSpawnSpec({
    fakeAppserver: true,
    runtime: null,
    repoRoot: 'D:\\dev\\RxyCode-master',
    scriptsDir: 'C:\\scripts'
  })
  assert.equal(spec.command, process.execPath)
  assert.deepEqual(spec.args, [join('C:\\scripts', 'fake-appserver.mjs')])
  assert.equal(spec.env.ELECTRON_RUN_AS_NODE, '1')
})

test('buildSpawnSpec always sets UTF-8 python env', () => {
  const spec = buildSpawnSpec({ runtime: null, repoRoot: 'D:\\dev' })
  assert.equal(spec.env.PYTHONUNBUFFERED, '1')
  assert.equal(spec.env.PYTHONIOENCODING, 'utf-8')
})

test('buildSpawnSpec sets the stub flag when requested', () => {
  const spec = buildSpawnSpec({ stub: true, runtime: null, repoRoot: 'D:\\dev' })
  assert.equal(spec.env.RXYCODE_APPSERVER_STUB, '1')
})

test('buildSpawnSpec does not set the stub flag otherwise', () => {
  const spec = buildSpawnSpec({ runtime: null, repoRoot: 'D:\\dev' })
  assert.equal(spec.env.RXYCODE_APPSERVER_STUB, undefined)
})

test('buildSpawnSpec sets preempt for real python appserver, not fake mode', () => {
  const real = buildSpawnSpec({ runtime: null, repoRoot: 'D:\\dev' })
  assert.equal(real.env.RXYCODE_APPSERVER_PREEMPT, '1')
  const fake = buildSpawnSpec({
    fakeAppserver: true,
    runtime: null,
    repoRoot: 'D:\\dev',
    scriptsDir: 'C:\\scripts'
  })
  assert.equal(fake.env.RXYCODE_APPSERVER_PREEMPT, undefined)
})

test('buildSpawnSpec throws when neither runtime nor repo root is available', () => {
  assert.throws(
    () => buildSpawnSpec({ runtime: null, repoRoot: null }),
    /bundled runtime.*repository root/
  )
})

test('manager constructor tolerates a missing dev repo when no runtime is set', () => {
  const base = fixtureDir()
  try {
    const manager = new AppServerManager({ cwd: base, runtime: null })
    assert.equal(manager.runtimeLabel, 'dev')
    assert.equal(manager.repoRootDir, '')
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test('manager start throws a clear error when no runtime and no repo root exist', () => {
  const base = fixtureDir()
  try {
    const manager = new AppServerManager({ cwd: base, runtime: null })
    assert.throws(() => manager.start(), /bundled runtime or a repository root/)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test('manager reports bundled label and app dir when a runtime is provided', () => {
  const base = fixtureDir()
  try {
    const runtime = fakeRuntime(base)
    const manager = new AppServerManager({ cwd: base, runtime })
    assert.equal(manager.runtimeLabel, 'bundled')
    assert.equal(manager.repoRootDir, runtime.appDir)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test('manager reports fake label for fake appserver mode', () => {
  const base = fixtureDir()
  try {
    const manager = new AppServerManager({ cwd: base, runtime: null, fakeAppserver: true })
    assert.equal(manager.runtimeLabel, 'fake')
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test('manager prefers the bundled runtime even when a repo root would resolve', () => {
  const base = fixtureDir()
  try {
    const runtime = fakeRuntime(base)
    const manager = new AppServerManager({ cwd: 'D:\\dev\\RxyCode-master', runtime })
    assert.equal(manager.runtimeLabel, 'bundled')
    assert.equal(manager.repoRootDir, runtime.appDir)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})
