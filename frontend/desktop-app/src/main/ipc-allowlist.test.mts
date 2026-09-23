import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  assertIpcInvoke,
  IpcAllowlistError,
  IPC_INVOKE_CHANNELS,
  isAllowedIpcChannel,
  validateIpcInvoke
} from './ipc-allowlist.ts'

test('H3: unknown IPC method is rejected', () => {
  assert.equal(isAllowedIpcChannel('appserver:rm-rf'), false)
  const result = validateIpcInvoke('fs:readFile', [])
  assert.equal(result.ok, false)
  if (!result.ok) assert.equal(result.code, 'unknown_method')
  assert.throws(() => assertIpcInvoke('shell:openPath', []), IpcAllowlistError)
})

test('H3: known IPC with invalid params is rejected', () => {
  assert.equal(validateIpcInvoke('appserver:send-line', [1]).ok, false)
  assert.equal(validateIpcInvoke('crash-report:set-consent', ['yes']).ok, false)
  assert.equal(validateIpcInvoke('appserver:send-line', ['{"jsonrpc":"2.0"}']).ok, true)
  assert.equal(validateIpcInvoke('crash-report:set-consent', [true]).ok, true)
  assert.equal(validateIpcInvoke('workspace:reveal', ['D:\\work']).ok, true)
  assert.equal(validateIpcInvoke('workspace:reveal', ['']).ok, false)
  assert.equal(validateIpcInvoke('workspace:reveal', []).ok, false)
  assert.throws(() => assertIpcInvoke('shell:openPath', ['D:\\work']), IpcAllowlistError)
})

test('H3: allowlist does not include Node/fs/child_process channels', () => {
  for (const channel of IPC_INVOKE_CHANNELS) {
    assert.equal(channel.includes('fs:'), false)
    assert.equal(channel.includes('child_process'), false)
    assert.equal(channel.includes('ipcRenderer'), false)
  }
})
