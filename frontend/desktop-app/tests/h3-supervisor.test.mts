import assert from 'node:assert/strict'
import { test } from 'node:test'
import { webPreferencesSafe } from '../src/main/web-preferences.ts'
import { assertIpcInvoke, IpcAllowlistError } from '../src/main/ipc-allowlist.ts'
import { isSafeExternalUrl } from '../src/main/external-url.ts'

test('H3: BrowserWindow uses isolated sandbox prefs (DC-J7)', () => {
  const prefs = webPreferencesSafe({
    preload: '/tmp/preload.js'
  })
  assert.equal(prefs.contextIsolation, true)
  assert.equal(prefs.nodeIntegration, false)
  assert.equal(prefs.sandbox, true)
  assert.equal(prefs.preload, '/tmp/preload.js')
})

test('H3: unknown IPC method/params are rejected', () => {
  assert.throws(() => assertIpcInvoke('shell:openPath', ['C:\\\\Windows']), (error: unknown) => {
    return error instanceof IpcAllowlistError && error.code === 'unknown_method'
  })
  assert.throws(() => assertIpcInvoke('appserver:send-line', []), (error: unknown) => {
    return error instanceof IpcAllowlistError && error.code === 'invalid_params'
  })
})

test('H3: external URLs are delegated, local schemes are not', () => {
  assert.equal(isSafeExternalUrl('https://example.com'), true)
  assert.equal(isSafeExternalUrl('file:///etc/passwd'), false)
})
